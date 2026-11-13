"""Independent OpenEXR library fixtures, including a final partial ZIP block."""
from pathlib import Path
from copy import deepcopy
import hashlib
import struct
import tempfile
import unittest
from unittest import mock
from dcc_task_runtime.exr_codec import read_exr, write_exr, encode_tiny_exr, ExrDecodeError, _parse_header
from dcc_task_runtime.denoise_blend import blend_pixels
ROOT = Path(__file__).resolve().parents[2]

class ExrNativeLibraryFixtureTests(unittest.TestCase):
    def test_malformed_native_color_attributes_are_rejected(self):
        from dcc_task_runtime.exr_codec import _attribute
        payload = encode_tiny_exr()
        _, cursor = _parse_header(payload)
        for attr in (_attribute('oiio:ColorSpace', 'float', b'abcd'),
                     _attribute('oiio:ColorSpace', 'string', b'\xff'),
                     _attribute('chromaticities', 'chromaticities', b'x'),
                     _attribute('chromaticities', 'chromaticities', struct.pack('<8f', *([float('nan')] * 8)))):
            with self.subTest(attr=attr), self.assertRaises(ExrDecodeError):
                _parse_header(payload[:cursor - 1] + attr + payload[cursor - 1:])

    def test_color_metadata_round_trip_preserves_native_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.exr'
            source.write_bytes(encode_tiny_exr())
            decoded = read_exr(source)
            color = {'oiio:ColorSpace': 'lin_rec709',
                     'chromaticities': [0.64, 0.33, 0.30, 0.60, 0.15, 0.06, 0.3127, 0.3290]}
            decoded['color_metadata'] = color
            target = Path(directory) / 'target.exr'
            write_exr(target, decoded, decoded['rows'])
            actual = read_exr(target)['color_metadata']
            self.assertEqual(actual['oiio:ColorSpace'], color['oiio:ColorSpace'])
            for a, b in zip(actual['chromaticities'], color['chromaticities']):
                self.assertAlmostEqual(a, b, places=6)
            for invalid in ({'oiio:ColorSpace': ''}, {'chromaticities': [float('nan')] * 8},
                            {'chromaticities': [0.0] * 7}):
                decoded['color_metadata'] = invalid
                with self.subTest(invalid=invalid), self.assertRaises(ExrDecodeError):
                    write_exr(target, decoded, decoded['rows'])

    def test_native_library_none_zips_zip_multichannel_mixed_samples(self):
        for compression in (0,2,3):
            with self.subTest(compression=compression):
                result=read_exr(ROOT/f'tests/fixtures/exr/openexr-3.4.15-{compression}.exr')
                self.assertEqual((result['width'],result['height']),(32,19))
                self.assertEqual(result['channels'],['R','depth.Z','id'])
                self.assertEqual(result['compression'],compression)
                probe=read_exr(ROOT/f'tests/fixtures/exr/openexr-3.4.15-{compression}.exr',with_pixels=False)
                self.assertEqual(probe['rows'],[])
                self.assertEqual(probe['sample_count'],32*19*3)
                for row in result['rows']:
                    y=row['y']
                    for x in (0,7,31):
                        self.assertAlmostEqual(row['channels']['R'][x],y+x/32,places=2)
                        self.assertAlmostEqual(row['channels']['depth.Z'][x],(y*100+x)/7,places=4)
                        self.assertEqual(row['channels']['id'][x],((y*32+x)*2654435761)&0xffffffff)

    def test_zip_truncation_duplicate_offsets_and_bad_block_rejected(self):
        raw=(ROOT/'tests/fixtures/exr/openexr-3.4.15-3.exr').read_bytes()
        _,table=_parse_header(raw)
        duplicate=bytearray(raw);duplicate[table+8:table+16]=duplicate[table:table+8]
        corrupt=bytearray(raw);offset=struct.unpack_from('<Q',raw,table)[0];corrupt[offset+8]^=127
        misaligned=bytearray(raw);struct.pack_into('<i',misaligned,offset,1)
        duplicate_channel=raw.replace(b'depth.Z\0',b'R\0depth',1)
        for label,data in [('truncated',raw[:-1]),('duplicate',duplicate),('duplicate_channel',duplicate_channel),('corrupt',corrupt),('misaligned',misaligned)]:
            with self.subTest(case=label),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'bad.exr';p.write_bytes(data)
                with self.assertRaises(ExrDecodeError):read_exr(p)

    def test_typed_none_roundtrip_real_blend_and_derived_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'output.exr'
            for compression,line_order in ((0,0),(2,1),(3,0)):
                raw=read_exr(ROOT/f'tests/fixtures/exr/openexr-3.4.15-{compression}.exr')
                denoised=deepcopy(raw)
                for row in denoised['rows']:
                    row['channels']['R']=[v+0.5 for v in row['channels']['R']]
                rows=blend_pixels(raw,denoised,.25)
                raw['header_fields']['line_order']=line_order
                before=deepcopy((raw,denoised,rows))
                receipt=write_exr(target,raw,rows)
                result=read_exr(target)
                self.assertEqual(result['compression'],0)
                self.assertEqual(result['channel_layout'],raw['channel_layout'])
                self.assertEqual(result['header_fields'],raw['header_fields'])
                self.assertEqual(result['rows'],rows)
                self.assertEqual(receipt['sha256'],hashlib.sha256(target.read_bytes()).hexdigest())
                self.assertEqual(receipt['bytes'],target.stat().st_size)
                self.assertEqual((raw,denoised,rows),before)
            # This negative-window/alpha case is derived from native mixed
            # samples; it is not an independently produced native fixture.
            derived=deepcopy(raw)
            derived['channel_layout']['data_window']=[-8,-4,23,14]
            derived['channel_layout']['display_window']=[-20,-10,40,30]
            derived['header_fields']={'line_order':1,'pixel_aspect_ratio':1.25,
                'screen_window_center':[-.5,2.0],'screen_window_width':0.0}
            alpha={'name':'beauty.A','pixel_type':1,'p_linear':1,'x_sampling':1,'y_sampling':1}
            derived['channel_layout']['channels'].insert(1,alpha)
            derived['channels'].insert(1,'beauty.A')
            derived['sample_count']+=derived['pixel_count']
            for row in derived['rows']:
                row['y']-=4
                row['channels']['beauty.A']=[.5]*derived['width']
            changed=deepcopy(derived)
            for row in changed['rows']:
                row['channels']['depth.Z']=[v+.123456789 for v in row['channels']['depth.Z']]
            rows=blend_pixels(derived,changed,.25)
            write_exr(target,derived,rows)
            result=read_exr(target)
            self.assertEqual(result['channel_layout'],derived['channel_layout'])
            self.assertEqual(result['header_fields'],derived['header_fields'])
            for actual,expected in zip(result['rows'],rows):
                self.assertEqual(actual['y'],expected['y'])
                self.assertEqual(actual['channels']['id'],expected['channels']['id'])
                self.assertTrue(all(type(v) is int for v in actual['channels']['id']))
                self.assertEqual(actual['channels']['beauty.A'],expected['channels']['beauty.A'])
                self.assertEqual(actual['channels']['depth.Z'],[struct.unpack('<f',struct.pack('<f',v))[0] for v in expected['channels']['depth.Z']])
            tiny=Path(directory)/'tiny.exr';tiny.write_bytes(encode_tiny_exr())
            self.assertEqual(read_exr(tiny)['rows'][0]['channels']['R'],[1.0])
            boundary=deepcopy(raw)
            limit=0x7fffffff//2-1
            boundary['channel_layout']['display_window']=[-limit,0,limit,18]
            for aspect in (1e-6,1e6):
                boundary['header_fields']['pixel_aspect_ratio']=aspect
                write_exr(target,boundary,boundary['rows'])
                self.assertEqual(read_exr(target)['channel_layout'],boundary['channel_layout'])

    def test_writer_rejects_range_coverage_layout_and_budget_before_io(self):
        raw=read_exr(ROOT/'tests/fixtures/exr/openexr-3.4.15-3.exr')
        bad=[]
        image=deepcopy(raw);image['rows'][0]['channels']['R'][0]=65520.;bad.append(('HALF overflow',image))
        image=deepcopy(raw);image['rows'][0]['channels']['depth.Z'][0]=float('nan');bad.append(('nonfinite',image))
        image=deepcopy(raw);image['rows'][0]['channels']['depth.Z'][0]=1e100;bad.append(('FLOAT overflow',image))
        for sample in (-1,0x100000000,1.0):
            image=deepcopy(raw);image['rows'][0]['channels']['id'][0]=sample;bad.append(('UINT bounds/type',image))
        image=deepcopy(raw);image['rows'].pop();bad.append(('coverage',image))
        image=deepcopy(raw);image['rows'][0]['y']=-1;bad.append(('y index',image))
        image=deepcopy(raw);image['channel_layout']['channels'][0]['x_sampling']=2;bad.append(('layout',image))
        image=deepcopy(raw);image['rows'][0]['channels']['R'].pop();bad.append(('sample count',image))
        image=deepcopy(raw);image['header_fields']['line_order']=2;bad.append(('scanline RANDOM_Y',image))
        image=deepcopy(raw);image['header_fields']['screen_window_width']=-1;bad.append(('negative screen width',image))
        image=deepcopy(raw);image['header_fields']['pixel_aspect_ratio']=1e-8;bad.append(('native aspect range',image))
        image=deepcopy(raw);image['channel_layout']['display_window']=[-0x80000000,0,0x7fffffff,18];bad.append(('display overflow',image))
        image=deepcopy(raw);image['channel_layout']['data_window']=[0x7fffffff-31,0,0x7fffffff,18];bad.append(('native data coordinate range',image))
        image=deepcopy(raw);image['channels'].reverse();image['channel_layout']['channels'].reverse();bad.append(('noncanonical channel order',image))
        image=deepcopy(raw);image.update(width=1,height=1_000_000,pixel_count=1_000_000,sample_count=3_000_000)
        image['channel_layout']['data_window']=[0,0,0,999_999];bad.append(('row object budget',image))
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing.exr';target.write_bytes(b'existing-output')
            for label,image in bad:
                with self.subTest(case=label),mock.patch('dcc_task_runtime.exr_codec.tempfile.mkstemp',side_effect=AssertionError('invalid writer input reached IO')):
                    with self.assertRaises(ExrDecodeError):write_exr(target,image,image['rows'])
                self.assertEqual(target.read_bytes(),b'existing-output')
                self.assertEqual(list(Path(directory).iterdir()),[target])
            valid=Path(directory)/'valid.exr';write_exr(valid,raw,raw['rows'])
            data=valid.read_bytes()
            # Malformed on-disk headers must also be rejected by the reader.
            reversed_channels=b''.join(c['name'].encode()+b'\0'+struct.pack('<iB3xii',c['pixel_type'],c['p_linear'],c['x_sampling'],c['y_sampling'])
                for c in reversed(raw['channel_layout']['channels']))+b'\0'
            for attribute,kind,payload in [('lineOrder','lineOrder',b'\2'),
                    ('screenWindowWidth','float',struct.pack('<f',-1)),
                    ('displayWindow','box2i',struct.pack('<4i',-0x80000000,0,0x7fffffff,18)),
                    ('channels','chlist',reversed_channels)]:
                marker=attribute.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<I',len(payload))
                start=data.index(marker)+len(marker)
                malformed=Path(directory)/'malformed.exr';malformed.write_bytes(data[:start]+payload+data[start+len(payload):])
                with self.subTest(reader_attribute=attribute),self.assertRaises(ExrDecodeError):read_exr(malformed)

    def test_writer_atomic_readback_and_replace_failures_preserve_existing_file(self):
        raw=read_exr(ROOT/'tests/fixtures/exr/openexr-3.4.15-3.exr')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing.exr';target.write_bytes(b'existing-output')
            for failure in ('readback','pixels','replace'):
                if failure=='readback':
                    patch=mock.patch('dcc_task_runtime.exr_codec.read_exr',side_effect=ExrDecodeError('injected readback failure'))
                elif failure=='replace':
                    patch=mock.patch('dcc_task_runtime.exr_codec.os.replace',side_effect=OSError('injected replace failure'))
                else:
                    changed=deepcopy(raw);changed['compression']=0;changed['rows'][0]['channels']['id'][0]+=1
                    patch=mock.patch('dcc_task_runtime.exr_codec.read_exr',return_value=changed)
                with self.subTest(failure=failure),patch:
                    with self.assertRaises((ExrDecodeError,OSError)):write_exr(target,raw,raw['rows'])
                self.assertEqual(target.read_bytes(),b'existing-output')
                self.assertEqual(list(Path(directory).iterdir()),[target])
