hl.config({
    quirks = {
        skip_non_kms_dmabuf_formats = false,
    },
    cursor = {
        no_hardware_cursors = 1,
    },
    general = {
        allow_tearing = false,
    },
    render = {
        direct_scanout = 0,
    },
    decoration = {
        blur = {
            noise = 0.0,
            size = 6,
            passes = 2,
            contrast = 0.92,
            brightness = 1.0,
            vibrancy = 0.2,
        },
    },
})
