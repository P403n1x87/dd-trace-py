import re


_punc_regex = re.compile(r"[\w']+|[.,!?;~@#$%^&*()+/-]")


def _est_tokens(s):
    # type: (str) -> int
    """Provide a very rough estimate of the number of tokens.

    Approximate using the following assumptions:
        * English text
        * 1 token ~= 4 chars
        * 1 token ~= ¾ words

    Note that this function is 3x faster than tiktoken's encoding.
    """
    est1 = len(s) / 4
    est2 = len(_punc_regex.findall(s)) * 0.75
    est = round((1.5 * est1 + 0.5 * est2) / 2)
    return est
