import numpy as np
import seaborn


def parse_results(path):
    with open(path) as result_file:
        return eval(result_file.read().replace("results: ", ""))


def plot(py_versions, ddtrace_versions):
    results = [
        [parse_results(f"/tmp/results/{py}-{dd}") for dd in ddtrace_versions]
        for py in py_versions
    ]
    system_time = [[int(e["system.time"]) for e in r] for r in results]
    system_time = np.array(system_time)
    plot = seaborn.heatmap(
        system_time, xticklabels=py_versions, yticklabels=ddtrace_versions
    )
    plot.set_title("System Time")
    plot.set_xlabel("Python")
    plot.set_ylabel("ddtrace")
    plot.figure.savefig("/tmp/results/plot.png")
