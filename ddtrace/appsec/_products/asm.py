from ddtrace import config
from ddtrace.settings.asm import config as asm_config


def post_preload():
    pass


def start():
    if asm_config._asm_enabled or config._remote_config_enabled:
        from ddtrace.appsec._remoteconfiguration import enable_appsec_rc

        enable_appsec_rc()


def restart(join=False):
    if asm_config._asm_enabled or config._remote_config_enabled:
        from ddtrace.appsec._remoteconfiguration import _forksafe_appsec_rc

        _forksafe_appsec_rc()


def stop(join=False):
    if asm_config._asm_enabled or config._remote_config_enabled:
        from ddtrace.appsec._remoteconfiguration import disable_appsec_rc

        disable_appsec_rc()


def at_exit(join=False):
    stop(join=join)
