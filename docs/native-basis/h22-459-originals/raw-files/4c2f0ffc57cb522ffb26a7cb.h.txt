/*
 * PROPRIETARY INFORMATION.  This software is proprietary to
 * Side Effects Software Inc., and is not to be reproduced,
 * transmitted, or disclosed in any way without written permission.
 *
 * NAME:	PXL_OCIO.h (UT Library, C++)
 *
 * COMMENTS:
 */

#ifndef __PXL_OCIO__
#define __PXL_OCIO__

#include "PXL_API.h"
#include "PXL_Common.h"
#include <SYS/SYS_Types.h>
#include <UT/UT_Functor.h>

class UT_StringHolder;
class UT_StringRef;
class UT_StringArray;
class UT_Options;

/// Abstract interface to OpenColorIO
namespace PXL_OCIO
{
    /// @{
    /// Private classes
    class ColorSpace;
    class Processor;
    /// @}

    /// Mirrors the OCIO enum so that we don't have to expose the
    /// OCIO_NAMESPACE and we can avoid namespace collisions.
    enum class BitDepth
    {
        PXL_BIT_DEPTH_UNKNOWN = 0,
        PXL_BIT_DEPTH_UINT8,
        PXL_BIT_DEPTH_UINT10,
        PXL_BIT_DEPTH_UINT12,
        PXL_BIT_DEPTH_UINT14,
        PXL_BIT_DEPTH_UINT16,
        PXL_BIT_DEPTH_UINT32,   // Like OCIO, historical reasons, but not supported
        PXL_BIT_DEPTH_F16,
        PXL_BIT_DEPTH_F32
    };

    static constexpr BitDepth DefaultBitDepth = BitDepth::PXL_BIT_DEPTH_F32;

    struct PXL_API PHandle
    {
        bool    isValid() const;
        bool    isNoOp() const;
        bool    is3D() const;
        void    clear() { myProcessor = nullptr; }
        explicit operator bool() const { return isValid(); }

        Processor       *myProcessor = nullptr;
        int              myLoadID = 0;
    };

    /// The path and filename of the config file being used.
    PXL_API const UT_StringRef &configFilePath();

    /// Returns whether the user has set $OCIO, $OCIO_ACTIVE_DISPLAYS or
    /// $OCIO_ACTIVE_VIEWS is set.  If there's an error loading the
    /// configuration, this method will return @c false.
    PXL_API bool	isOCIOEnvSet(bool check_for_active_vars=true);

    /// Returns the current color space name
    PXL_API const char	*getDefaultDisplay();

    /// Returns the current color space name
    PXL_API const char	*getDefaultView(const char *display = NULL);

    /// Return the list of views for a given display.
    PXL_API bool	getViewsForDisplay(const char *display,
                                           UT_StringArray &view_names);

    /// Returns the list of active displays
    PXL_API void 	getActiveDisplays(UT_StringArray &names);

    /// Returns the list of active views
    PXL_API void	getActiveViews(UT_StringArray &names);

    /// Returns a list of the supported color spaces
    PXL_API void	getColorSpaces(UT_StringArray &names);

    /// Returns a list of looks (color transforms)
    PXL_API void getLooks(UT_StringArray &looks);

    /// Returns a list of the supported roles
    PXL_API void        getRoles(UT_StringArray &names);

    /// Reload the configuration.
    PXL_API void        reload();

    PXL_API const char *getDefaultRole();
    PXL_API const char *getReferenceRole();
    PXL_API const char *getDataRole();
    PXL_API const char *getSceneLinearRole();
    PXL_API const char *getCompLogRole();
    PXL_API const char *getColorPickingRole();

    // Return the name of the color space associated with the "scene_linear" role
    PXL_API const UT_StringHolder       &getSceneLinearColorSpace();

    // find an sRGB color space in the given config file.
    PXL_API const UT_StringHolder       &getsRGBColorSpace();
    PXL_API UT_StringHolder              getsRGBColorSpace(const char *display);

    /// @{
    /// Test whether a color space is one of the well-known color spaces
    PXL_API bool        issRGB(const ColorSpace *s);
    PXL_API bool        isRec709(const ColorSpace *s);
    PXL_API bool        isLinearRec709(const ColorSpace *s);
    PXL_API bool        isSceneLinear(const ColorSpace *s);
    PXL_API bool        isRaw(const ColorSpace *s);
    /// @}

    // find an rec709 color space in the given config file
    PXL_API const UT_StringHolder &getRec709ColorSpace();

    // find a linear rec709 color space in the given config file
    PXL_API const UT_StringHolder &getLinearRec709ColorSpace();

    // Find a raw color space
    PXL_API const UT_StringHolder &getRawColorSpace();

    /// Return the colorspace defined by the view for a given display.
    PXL_API const char *getColorSpaceForDisplayView(const char *display_name,
						   const char *view_name);

    /// Return the colorspace defined by the view for a given display.
    PXL_API const char *getTransformNameForDisplayView(const char *display_name,
                                                      const char *view_name);

    /// Return the looks attached to the view for a given display.
    PXL_API const char *getLooksForDisplayView(const char *display_name,
					      const char *view_name);


    /// Guess at the colorspace using the rightmost colorspace found, or NULL
    /// if none are found.
    PXL_API const char *parseColorSpaceFromString(const char *string);

    PXL_API UT_StringHolder parseColorSpaceFromHolder(const UT_StringHolder &s);

    /// Convert a PXL_ColorSpace to roughly the OCIO equivalent
    PXL_API const UT_StringHolder &pxlImageColorSpace(PXL_ColorSpace cs,
                                            const UT_StringHolder &ocioname);

    /// @{
    /// Get the best approximation for the PXL_ColorSpace from the OCIO color
    /// space.  The @c name will be filled out with the full name of the space.
    /// The return value will be PXL_CS_OCIO, unless it's a well known space.
    PXL_API PXL_ColorSpace      pxlImageColorSpace(const ColorSpace *cs,
                                        UT_StringHolder &name);
    PXL_API PXL_ColorSpace      pxlImageColorSpace(const UT_StringHolder &csname,
                                        UT_StringHolder &name);
    /// @}


    /// Return a color space handle given a name.  The name may be a color
    /// space name or prefixed with "role:" to specify a color space role.
    PXL_API const ColorSpace	*lookupSpace(const UT_StringHolder &name);

    /// Return the name of the color space
    PXL_API const char	*getName(const ColorSpace *space);
    /// Return the description of the color space
    PXL_API const char	*getDescription(const ColorSpace *space);
    /// Return the Nanocolor name for the color space.  If it's not possible to
    /// determine the Nanocolor space name, this will return an empty string.
    PXL_API const UT_StringHolder &getNanocolorName(const ColorSpace *space);
    /// Return the OpenUSD color space token:
    /// See: https://openusd.org/release/user_guides/color_user_guide.html
    PXL_API const UT_StringHolder &getOpenUSDName(const ColorSpace *space);
    /// Return the "best" alias for the color space (either Nanocolor or OpenUSD)
    PXL_API const UT_StringHolder &getBestAlias(const ColorSpace *space);

    /// Return the allocation variable meta data about the color space
    PXL_API bool	getAllocationVars(const ColorSpace* space,
				bool &uniform,
				fpreal &min,
				fpreal &max,
				fpreal &offset);
    /// Set 'fp' to true if the color space is defined for FP, false for uint
    PXL_API bool	isFloatPointSpace(const ColorSpace* space,
					  bool &fp);
    /// Return a list of the aliases for a color space
    PXL_API void        getAliases(const ColorSpace *space,
                                    UT_StringArray &aliases);

    /// Fill out metadata for color space in a UT_Options
    /// Keys are the tokens in the config.ocio file:
    ///	- @c name
    ///	- @c family
    ///	- @c equalitygroup
    ///	- @c bitdepth
    ///	- @c description
    ///	- @c isdata
    ///	- @c allocation
    ///	- @c allocationvars
    PXL_API bool	getInfo(const ColorSpace *space, UT_Options &info);

    /// Get the viewing rule names
    PXL_API void        viewingRuleNames(UT_StringArray &names);
    /// Lookup a viewing rule by the name
    PXL_API const UT_Options     &viewingRule(const UT_StringRef &name);

    /// @{
    /// Lookup processors which can be used to transform colors efficiently.
    /// @note: These processors become invalid on a reload.
    PXL_API PHandle     lookupProcessor(const UT_StringHolder &src,
                                    const UT_StringHolder &dest,
                                    const UT_StringHolder &looks,
                                    bool forward_transform=true,
                                    const BitDepth src_depth=DefaultBitDepth,
                                    const BitDepth dst_depth=DefaultBitDepth);
    PXL_API PHandle     lookupProcessor(const ColorSpace *src,
                                    const ColorSpace *dest,
                                    const UT_StringHolder &looks,
                                    bool forward_transform=true,
                                    const BitDepth src_depth=DefaultBitDepth,
                                    const BitDepth dst_depth=DefaultBitDepth);
    PXL_API PHandle     lookupViewProcessor(const UT_StringHolder &src,
                                    const UT_StringHolder &display,
                                    const UT_StringHolder &view,
                                    bool forward_transform,
                                    const BitDepth src_depth=DefaultBitDepth,
                                    const BitDepth dst_depth=DefaultBitDepth);
    PXL_API PHandle     lookupViewProcessor(
                                    const UT_StringHolder &view_transform,
                                    bool forward_transform,
                                    const BitDepth src_depth=DefaultBitDepth,
                                    const BitDepth dst_depth=DefaultBitDepth);
    /// @}

    /// Transform pixels by a processor
    PXL_API bool        transform(const PHandle &processor,
                                fpreal32 *data, const int npixels,
                                const int nchannels);
    PXL_API bool        transform(const PHandle &processor,
                                const void *src, void *dst, const int width,
                                const int height, const int src_channels,
                                const int dst_channels);

    // Process buffer in-place
    PXL_API bool        transform(const PHandle &processor,
                                void *data, int width, int height, int channels);

    /// @{
    /// Is there a transform from src->dest with the applied looks.
    inline bool         isValidTransform(const PHandle &processor)
    {
        return processor.isValid();
    }
    /// @}

    /// @{
    /// Valid transform, but does nothing.  This is true if the src and dest
    /// color spaces are equal, but also handles special cases like
    /// transforming from "raw" spaces.  So, this is more correct than an
    /// operator==() or isEqual() method.
    inline bool         isNoOpTransform(const PHandle &processor)
    {
        return processor.isNoOp();
    }
    /// @}

    /// @{
    /// Does the transform from src->dest with applied looks require a 3D LUT.
    inline bool         is3DTransform(const PHandle &processor)
    {
        return processor.is3D();
    }
    /// @}

    /// @{
    /// Transform color data from one color space to another color space.
    /// The color space names may either refer to a color space name, or it can
    /// also be prefixed with "role:" and refer to a color space role. The
    /// 'looks' is a comma separated list of color gradings (aka looks)
    inline bool	transform(const UT_StringHolder &src,
			  const UT_StringHolder &dest,
			  const UT_StringHolder &looks,
			  fpreal32 *data, int npixels, int nchannels,
                          bool forward_transform = true)
    {
        return transform(lookupProcessor(src, dest, looks, forward_transform),
                        data, npixels, nchannels);
    }
    inline bool	transform(const ColorSpace *src,
			  const ColorSpace *dest,
			  const UT_StringHolder &looks,
			  fpreal32 *data, int npixels, int nchannels,
                          bool forward_transform = true)
    {
        return transform(lookupProcessor(src, dest, looks, forward_transform),
                        data, npixels, nchannels);
    }
    /// @}

    /// Transform from a colorspace to a display/view, including looks.
    inline bool	transformToView(const UT_StringHolder &src,
				const UT_StringHolder &display,
				const UT_StringHolder &view,
				fpreal32 *data, int npixels, int nchannels,
                                bool forward_xform = true)
    {
        return transform(lookupViewProcessor(src, display, view, forward_xform),
                        data, npixels, nchannels);
    }

    /// Transform with the given view transform, which must exist in the config
    inline bool	transform(const UT_StringHolder &view_transform,
                          fpreal32 *data, int npixels, int nchannels,
                          bool forward_transform = true)
    {
        return transform(lookupViewProcessor(view_transform, forward_transform),
                        data, npixels, nchannels);
    }

    /// @{
    /// When the OCIO config is reloaded, all processor and color space
    /// pointers become invalid.  You can register a callback (and remove it)
    /// to be notified of reloads.
    PXL_API int         addConfigChangeCB(UT_Functor<void> callback);
    PXL_API void        removeConfigChangeCB(int id);
    /// @}

} // end PXL_OCIO namespace

#endif
