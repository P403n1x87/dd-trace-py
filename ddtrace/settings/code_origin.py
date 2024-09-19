from envier import En


class CodeOriginConfig(En):
    __prefix__ = "dd.code_origin"

    max_frame_depth = En.v(
        int,
        "max_frame_depth",
        default=8,
        help_type="Integer",
        help="Maximum number of frames to capture for code origin",
        private=True,
    )

    class SpanCodeOriginConfig(En):
        __prefix__ = "for_spans"
        __item__ = "span"

        enabled = En.v(
            bool,
            "enabled",
            default=False,
            help_type="Boolean",
            help="Enable code origin for spans",
        )


config = CodeOriginConfig()
