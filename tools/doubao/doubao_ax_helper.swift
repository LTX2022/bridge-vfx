import AppKit
import ApplicationServices
import CommonCrypto
import Foundation
import Security

private let schema = "bridge.doubao_ax/1.0"
private let bundleID = "com.bot.pc.doubao"
private let maxPromptBytes = 64 * 1024
private let maxResponseBytes = 1024 * 1024

private struct HelperFailure: Error {
    let code: String
    let message: String
    let details: [String: Any]
}

private struct Options {
    let operation: String
    let appPath: String
    let sessionID: String?
    let guardFingerprint: String?
    let inputClass: String?
    let text: String?
}

private struct AppIdentity {
    let path: String
    let bundleURL: URL
    let version: String
    let executableSHA256: String
    let codeSignature: String
}

private struct ControlCandidate {
    let element: AXUIElement
    let role: String
    let identifier: String
    let title: String
    let enabled: Bool
    let value: String
    let score: Int
}

private struct ControlSelection {
    let candidate: ControlCandidate?
    let count: Int
}

private struct ControlSnapshot {
    let descriptor: [String: Any]
    let candidate: ControlCandidate?
}

private func fail(_ code: String, _ message: String, _ details: [String: Any] = [:]) -> HelperFailure {
    return HelperFailure(code: code, message: message, details: details)
}

private func emit(_ object: [String: Any], exitCode: Int32 = 0) -> Never {
    do {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        let fallback = "{\"schema\":\"\(schema)\",\"ok\":false,\"code\":\"HELPER_PROTOCOL_ERROR\",\"message\":\"could not encode helper response\"}\n"
        FileHandle.standardOutput.write(Data(fallback.utf8))
        Darwin.exit(70)
    }
    Darwin.exit(exitCode)
}

private func validHex(_ value: String, length: Int) -> Bool {
    guard value.count == length else { return false }
    return value.unicodeScalars.allSatisfy { scalar in
        (scalar.value >= 48 && scalar.value <= 57) ||
        (scalar.value >= 65 && scalar.value <= 70) ||
        (scalar.value >= 97 && scalar.value <= 102)
    }
}

private func parseOptions() throws -> Options {
    let args = Array(CommandLine.arguments.dropFirst())
    var values: [String: String] = [:]
    var index = 0
    while index < args.count {
        let flag = args[index]
        guard flag.hasPrefix("--"), index + 1 < args.count else {
            throw fail("INVALID_REQUEST", "helper arguments are incomplete")
        }
        guard ["--operation", "--app-path", "--session-id", "--guard-fingerprint", "--input-class", "--text"].contains(flag) else {
            throw fail("INVALID_REQUEST", "helper received an unsupported argument")
        }
        guard values[flag] == nil else {
            throw fail("INVALID_REQUEST", "helper argument was repeated")
        }
        values[flag] = args[index + 1]
        index += 2
    }
    guard let operation = values["--operation"],
          let appPath = values["--app-path"],
          ["probe", "snapshot", "new_task", "send_synthetic", "read_response"].contains(operation) else {
        throw fail("INVALID_REQUEST", "helper operation is not in the fixed vocabulary")
    }
    guard appPath.hasPrefix("/"), appPath.count <= 4096 else {
        throw fail("INVALID_REQUEST", "helper app path must be an absolute bounded path")
    }
    let sessionID = values["--session-id"]
    if let sessionID, !validHex(sessionID, length: 32) {
        throw fail("INVALID_REQUEST", "helper session id is invalid")
    }
    let guardFingerprint = values["--guard-fingerprint"]
    if let guardFingerprint, !validHex(guardFingerprint, length: 64) {
        throw fail("INVALID_REQUEST", "helper snapshot guard is invalid")
    }
    let inputClass = values["--input-class"]
    let text = values["--text"]
    let common: Set<String> = ["--operation", "--app-path"]
    var allowed = common
    switch operation {
    case "probe", "snapshot":
        allowed.formUnion(["--session-id"])
    case "new_task":
        allowed.formUnion(["--session-id", "--guard-fingerprint"])
        guard sessionID != nil, guardFingerprint != nil else {
            throw fail("INVALID_REQUEST", "new_task requires a session and snapshot guard")
        }
    case "send_synthetic":
        allowed.formUnion(["--session-id", "--guard-fingerprint", "--input-class", "--text"])
        guard sessionID != nil, guardFingerprint != nil, inputClass == "synthetic", let text else {
            throw fail("INVALID_REQUEST", "send_synthetic requires typed synthetic input")
        }
        guard !text.isEmpty, text.utf8.count <= maxPromptBytes, !text.unicodeScalars.contains(where: { $0.value == 0 }) else {
            throw fail("INVALID_REQUEST", "synthetic prompt is empty or exceeds the bound")
        }
    case "read_response":
        allowed.formUnion(["--session-id", "--guard-fingerprint"])
        guard sessionID != nil, guardFingerprint != nil else {
            throw fail("INVALID_REQUEST", "read_response requires a session and snapshot guard")
        }
    default:
        throw fail("INVALID_REQUEST", "helper operation is not supported")
    }
    let present = Set(values.keys)
    guard present.isSubset(of: allowed) else {
        throw fail("INVALID_REQUEST", "helper argument is not valid for this operation")
    }
    return Options(operation: operation, appPath: appPath, sessionID: sessionID, guardFingerprint: guardFingerprint, inputClass: inputClass, text: text)
}

private func sha256File(_ path: String) -> String {
    guard let handle = FileHandle(forReadingAtPath: path) else { return "" }
    defer { try? handle.close() }
    var context = CC_SHA256_CTX()
    CC_SHA256_Init(&context)
    while true {
        guard let chunk = try? handle.read(upToCount: 1024 * 1024), !chunk.isEmpty else { break }
        chunk.withUnsafeBytes { bytes in
            _ = CC_SHA256_Update(&context, bytes.baseAddress, CC_LONG(chunk.count))
        }
    }
    var output = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
    CC_SHA256_Final(&output, &context)
    return output.map { String(format: "%02x", $0) }.joined()
}

private func sha256Data(_ data: Data) -> String {
    var output = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
    data.withUnsafeBytes { bytes in
        _ = CC_SHA256(bytes.baseAddress, CC_LONG(data.count), &output)
    }
    return output.map { String(format: "%02x", $0) }.joined()
}

private func signingIdentity(_ path: String) -> String {
    var staticCode: SecStaticCode?
    guard SecStaticCodeCreateWithPath(URL(fileURLWithPath: path) as CFURL, SecCSFlags(), &staticCode) == errSecSuccess,
          let staticCode else { return "" }
    var rawInfo: CFDictionary?
    guard SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation), &rawInfo) == errSecSuccess,
          let info = rawInfo as? [String: Any] else { return "" }
    return (info[kSecCodeInfoUnique as String] as? String) ?? (info[kSecCodeInfoIdentifier as String] as? String) ?? ""
}

private func appIdentity(_ path: String) throws -> AppIdentity {
    let rawURL = URL(fileURLWithPath: path).standardizedFileURL
    let resolved = rawURL.resolvingSymlinksInPath()
    guard rawURL.path == resolved.path,
          rawURL.lastPathComponent == "Doubao",
          rawURL.pathComponents.suffix(3).elementsEqual(["Contents", "MacOS", "Doubao"]),
          FileManager.default.isExecutableFile(atPath: rawURL.path) else {
        throw fail("UI_CONTROL_UNVERIFIED", "Doubao requires the exact Contents/MacOS/Doubao executable")
    }
    let bundleURL = rawURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    guard bundleURL.pathExtension == "app", let bundle = Bundle(url: bundleURL), bundle.bundleIdentifier == bundleID else {
        throw fail("UI_CONTROL_UNVERIFIED", "Doubao bundle identity could not be verified")
    }
    let version = (bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
        ?? (bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String)
        ?? ""
    return AppIdentity(path: rawURL.path, bundleURL: bundleURL, version: version, executableSHA256: sha256File(rawURL.path), codeSignature: signingIdentity(rawURL.path))
}

private func axTrusted(applicationPath: String) throws {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: false] as CFDictionary
    guard AXIsProcessTrustedWithOptions(options) else {
        throw fail("AX_PERMISSION_REQUIRED", "macOS Accessibility permission is required for the native helper process", [
            "permission_target": CommandLine.arguments.first ?? "",
            "permission_scope": "Accessibility",
            "application_path": applicationPath,
        ])
    }
}

private func axAttribute(_ element: AXUIElement, _ name: String) -> Any? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}

private func axString(_ element: AXUIElement, _ name: String) -> String {
    if let value = axAttribute(element, name) as? String { return value }
    if let value = axAttribute(element, name) as? NSString { return value as String }
    if let value = axAttribute(element, name) as? NSAttributedString { return value.string }
    return ""
}

private func axBool(_ element: AXUIElement, _ name: String, fallback: Bool = true) -> Bool {
    if let value = axAttribute(element, name) as? Bool { return value }
    if let value = axAttribute(element, name) as? NSNumber { return value.boolValue }
    return fallback
}

private func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    guard let raw = axAttribute(element, kAXChildrenAttribute as String) else { return [] }
    if let children = raw as? [AXUIElement] { return children }
    return []
}

private func collect(_ root: AXUIElement) -> [ControlCandidate] {
    var result: [ControlCandidate] = []
    func visit(_ element: AXUIElement, depth: Int) {
        guard depth <= 40, result.count < 1200 else { return }
        let role = axString(element, kAXRoleAttribute as String)
        guard role != "AXMenuBar" else { return }
        let rawIdentifier = axString(element, kAXIdentifierAttribute as String)
        let identifier = rawIdentifier.isEmpty ? axString(element, "AXDOMIdentifier") : rawIdentifier
        let rawTitle = axString(element, kAXTitleAttribute as String)
        let title = rawTitle.isEmpty ? axString(element, kAXDescriptionAttribute as String) : rawTitle
        let value = axString(element, kAXValueAttribute as String)
        let enabled = axBool(element, kAXEnabledAttribute as String)
        let editable = axBool(element, "AXEditable", fallback: role == kAXTextFieldRole as String || role == kAXTextAreaRole as String)
        let score = editable ? 4 : 0
        result.append(ControlCandidate(element: element, role: role, identifier: identifier, title: title, enabled: enabled, value: value, score: score))
        for child in axChildren(element) { visit(child, depth: depth + 1) }
    }
    visit(root, depth: 0)
    // The observed 2.27 desktop build exposes New Conversation in File.
    // Read only that menu; never traverse Apple recent items or chat history menus.
    if let rawBar = axAttribute(root, kAXMenuBarAttribute as String) {
        let bar = rawBar as! AXUIElement
        for item in axChildren(bar) where ["文件", "File"].contains(axString(item, kAXTitleAttribute as String)) {
            for menu in axChildren(item) {
                for entry in axChildren(menu) where ["新建对话", "New Chat", "New Conversation"].contains(axString(entry, kAXTitleAttribute as String)) {
                    visit(entry, depth: 1)
                }
            }
        }
    }
    return result
}

private func normalized(_ value: String) -> String { value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }

private func containsToken(_ candidate: ControlCandidate, _ tokens: [String]) -> Bool {
    let haystack = normalized(candidate.title + " " + candidate.identifier + " " + candidate.value.prefix(160))
    return tokens.contains { haystack.contains($0) }
}

private func metadataContainsToken(_ candidate: ControlCandidate, _ tokens: [String]) -> Bool {
    let metadata = normalized(candidate.title + " " + candidate.identifier)
    return tokens.contains { metadata.contains($0) }
}

private func selectComposer(_ candidates: [ControlCandidate]) -> ControlSelection {
    let matches = candidates.filter {
        ($0.role == kAXTextAreaRole as String) && $0.enabled
    }
    return ControlSelection(candidate: matches.count == 1 ? matches[0] : nil, count: matches.count)
}

private func selectNewTask(_ candidates: [ControlCandidate]) -> ControlSelection {
    let tokens = ["new chat", "new conversation", "new task", "新对话", "新建对话", "开始新对话"]
    let matches = candidates.filter { ($0.role == kAXButtonRole as String || $0.role == "AXMenuItem") && $0.enabled && tokens.contains(normalized($0.title)) }
    return ControlSelection(candidate: matches.count == 1 ? matches[0] : nil, count: matches.count)
}

private func selectSend(_ candidates: [ControlCandidate]) -> ControlSelection {
    let tokens = ["send", "send message", "submit", "发送", "提交"]
    let matches = candidates.filter { $0.role == kAXButtonRole as String && $0.enabled && (tokens.contains(normalized($0.title)) || $0.identifier == "flow-end-msg-send") }
    return ControlSelection(candidate: matches.count == 1 ? matches[0] : nil, count: matches.count)
}

private func selectResponse(_ candidates: [ControlCandidate]) -> ControlSelection {
    let positive = ["response", "answer", "assistant", "reply", "content", "output", "回复", "回答", "助手", "内容", "输出"]
    let negative = ["prompt", "composer", "input", "history", "conversation", "user", "question", "输入", "历史", "会话", "用户", "问题"]
    let all = candidates.filter {
        $0.role == kAXStaticTextRole as String || $0.role == kAXTextAreaRole as String || $0.role == "AXWebArea"
    }
    let matches = all.filter {
        metadataContainsToken($0, positive) && !metadataContainsToken($0, negative)
    }
    guard !matches.isEmpty else { return ControlSelection(candidate: nil, count: 0) }
    let scored = matches.map { candidate -> ControlCandidate in
        let hint = metadataContainsToken(candidate, positive) ? 100 : 0
        let roleWeight = candidate.role == "AXWebArea" ? 40 : (candidate.role == kAXTextAreaRole as String ? 30 : 10)
        let length = min(candidate.value.count, 10)
        return ControlCandidate(element: candidate.element, role: candidate.role, identifier: candidate.identifier, title: candidate.title, enabled: candidate.enabled, value: candidate.value, score: hint + roleWeight + length)
    }.sorted { $0.score > $1.score }
    let selected = scored.first
    let tied = scored.filter { $0.score == selected?.score }.count
    return ControlSelection(candidate: tied == 1 ? selected : nil, count: scored.count)
}

private func responseIsBusy(_ candidates: [ControlCandidate]) -> Bool {
    let loadingTokens = ["loading", "generating", "working", "thinking", "生成中", "加载中", "处理中"]
    return candidates.contains { candidate in
        if axBool(candidate.element, "AXBusy", fallback: false) { return true }
        if ["AXProgressIndicator", "AXBusyIndicator", "AXSpinner"].contains(candidate.role) { return true }
        return metadataContainsToken(candidate, loadingTokens)
    }
}

private func descriptor(_ kind: String, _ selection: ControlSelection) -> ControlSnapshot {
    guard let candidate = selection.candidate else {
        return ControlSnapshot(descriptor: ["kind": kind, "available": false, "candidate_count": selection.count], candidate: nil)
    }
    return ControlSnapshot(descriptor: [
        "kind": kind,
        "available": true,
        "candidate_count": selection.count,
        "role": candidate.role,
        "identifier": candidate.identifier,
        "title": candidate.title,
        "enabled": candidate.enabled,
    ], candidate: candidate)
}

private func currentApp(_ identity: AppIdentity) throws -> (pid_t, AXUIElement) {
    try axTrusted(applicationPath: identity.path)
    let matches = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).filter {
        $0.executableURL?.resolvingSymlinksInPath().path == identity.path
    }
    guard matches.count == 1, let application = matches.first else {
        throw fail("UI_CONTROL_UNVERIFIED", "the exact Doubao executable is not running uniquely", ["matches": matches.count])
    }
    let root = AXUIElementCreateApplication(application.processIdentifier)
    AXUIElementSetMessagingTimeout(root, 0.5)
    return (application.processIdentifier, root)
}

private func makeSnapshot(_ identity: AppIdentity, sessionID: String?, root: AXUIElement) -> [String: Any] {
    let candidates = collect(root)
    let composer = descriptor("composer", selectComposer(candidates))
    let response = descriptor("response", selectResponse(candidates))
    let newTask = descriptor("new_task", selectNewTask(candidates))
    let controls: [String: Any] = ["composer": composer.descriptor, "response": response.descriptor, "new_task": newTask.descriptor]
    let fingerprintPayload: [String: Any] = ["app_path": identity.path, "bundle_id": bundleID, "pid": Int(rootPID(root)), "session_id": sessionID ?? "", "controls": controls]
    let fingerprint: String
    if let data = try? JSONSerialization.data(withJSONObject: fingerprintPayload, options: [.sortedKeys]) {
        fingerprint = sha256Data(data)
    } else {
        fingerprint = ""
    }
    return [
        "app_path": identity.path,
        "bundle_id": bundleID,
        "app_version": identity.version,
        "pid": Int(rootPID(root)),
        "session_id": sessionID ?? "",
        "code_signature": identity.codeSignature,
        "executable_sha256": identity.executableSHA256,
        "fingerprint": fingerprint,
        "controls": controls,
    ]
}

private func rootPID(_ root: AXUIElement) -> pid_t {
    var pid: pid_t = 0
    AXUIElementGetPid(root, &pid)
    return pid
}

private func checkedSnapshot(_ identity: AppIdentity, options: Options, root: AXUIElement) throws -> [String: Any] {
    let snapshot = makeSnapshot(identity, sessionID: options.operation == "new_task" ? nil : options.sessionID, root: root)
    guard let fingerprint = snapshot["fingerprint"] as? String, !fingerprint.isEmpty,
          let expected = options.guardFingerprint, fingerprint == expected else {
        throw fail("UI_CONTROL_UNVERIFIED", "the Doubao Accessibility tree changed since the snapshot guard", ["reason": "snapshot_changed"])
    }
    return snapshot
}

private func perform(_ options: Options, identity: AppIdentity) throws -> [String: Any] {
    let (_, root) = try currentApp(identity)
    switch options.operation {
    case "probe", "snapshot":
        return makeSnapshot(identity, sessionID: options.sessionID, root: root)
    case "new_task":
        let before = try checkedSnapshot(identity, options: options, root: root)
        let candidates = collect(root)
        let selection = selectNewTask(candidates)
        guard let button = selection.candidate else {
            throw fail("UI_CONTROL_UNVERIFIED", "the exact new-task Accessibility control was not uniquely identified", ["candidate_count": selection.count])
        }
        guard AXUIElementPerformAction(button.element, kAXPressAction as CFString) == .success else {
            throw fail("UI_CONTROL_UNVERIFIED", "the new-task Accessibility action was rejected")
        }
        Thread.sleep(forTimeInterval: 0.2)
        let sessionID = options.sessionID ?? ""
        let fresh = makeSnapshot(identity, sessionID: sessionID, root: root)
        let controls = fresh["controls"] as? [String: Any] ?? [:]
        let composer = controls["composer"] as? [String: Any]
        guard composer?["available"] as? Bool == true else {
            throw fail("UI_CONTROL_UNVERIFIED", "new task did not expose the composer control")
        }
        _ = before
        return ["session_id": sessionID, "snapshot": fresh]
    case "send_synthetic":
        let before = try checkedSnapshot(identity, options: options, root: root)
        let candidates = collect(root)
        let composer = selectComposer(candidates)
        guard let composerElement = composer.candidate else {
            throw fail("UI_CONTROL_UNVERIFIED", "composer control was not uniquely identified", ["composer_candidates": composer.count])
        }
        guard let text = options.text, AXUIElementSetAttributeValue(composerElement.element, kAXValueAttribute as CFString, text as CFTypeRef) == .success else {
            throw fail("UI_CONTROL_UNVERIFIED", "the composer rejected the synthetic prompt")
        }
        // The send button is enabled only after the draft has been entered.
        Thread.sleep(forTimeInterval: 0.15)
        let send = selectSend(collect(root))
        guard let sendElement = send.candidate else {
            throw fail("UI_CONTROL_UNVERIFIED", "draft entered but send control is not unique; no send action dispatched", ["draft_entered": true, "send_dispatched": false, "send_candidates": send.count])
        }
        guard AXUIElementPerformAction(sendElement.element, kAXPressAction as CFString) == .success else {
            throw fail("UI_CONTROL_UNVERIFIED", "the send Accessibility action was rejected")
        }
        let fresh = makeSnapshot(identity, sessionID: options.sessionID, root: root)
        guard before["fingerprint"] != nil else { throw fail("HELPER_PROTOCOL_ERROR", "snapshot guard was lost") }
        return ["session_id": options.sessionID ?? "", "accepted": true, "snapshot": fresh]
    case "read_response":
        _ = try checkedSnapshot(identity, options: options, root: root)
        let candidates = collect(root)
        let response = selectResponse(candidates)
        guard let responseElement = response.candidate, !responseIsBusy(candidates) else {
            return ["session_id": options.sessionID ?? "", "status": "pending", "complete": false]
        }
        let text = axString(responseElement.element, kAXValueAttribute as String)
        guard !text.isEmpty else {
            return ["session_id": options.sessionID ?? "", "status": "pending", "complete": false]
        }
        guard text.utf8.count <= maxResponseBytes else {
            throw fail("UI_CONTROL_UNVERIFIED", "the response control exceeded the bounded read size")
        }
        let fresh = makeSnapshot(identity, sessionID: options.sessionID, root: root)
        return ["session_id": options.sessionID ?? "", "status": "ready", "complete": true, "text": text, "snapshot": fresh]
    default:
        throw fail("INVALID_REQUEST", "helper operation is not supported")
    }
}

do {
    let options = try parseOptions()
    let identity = try appIdentity(options.appPath)
    let result = try perform(options, identity: identity)
    emit(["schema": schema, "ok": true, "operation": options.operation, "result": result])
} catch let error as HelperFailure {
    emit(["schema": schema, "ok": false, "code": error.code, "message": error.message, "details": error.details], exitCode: 1)
} catch {
    emit(["schema": schema, "ok": false, "code": "HELPER_PROTOCOL_ERROR", "message": "native helper failed", "details": [String: Any]()], exitCode: 70)
}
