from _config import config


def log(*args):
    print(*args, file=config.output_stream)
