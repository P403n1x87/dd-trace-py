import os
from itertools import product
import subprocess

import click
import docker
from rich.console import Console
from rich.progress import track
from scenarios.fat import FAT_DOCKERFILE
from scenarios.model import plot
import toml

CONSOLE = Console()
DOCKER = docker.from_env()


def get_matrix(path):
    with open(os.path.join(path, "matrix.toml")) as matrix_file:
        return toml.load(matrix_file)


def tag(scenario_name, venv):
    return f"ddtrace-{scenario_name}-{venv}"


def build_fat_image(scenario_name, py_versions, ddtrace_versions):
    with open("Dockerfile", "w") as dockerfile:
        dockerfile.write(
            FAT_DOCKERFILE.format(
                apt_py_versions=" ".join(["python" + py for py in py_versions]),
                py_versions=" ".join(f'"{py}"' for py in py_versions),
                ddtrace_versions=" ".join(f'"{dd}"' for dd in ddtrace_versions),
            )
        )
    DOCKER.images.build(
        path=os.getcwd(), tag="pyddmatrix"
    )  # TODO: Maybe use scenario_name?
    os.remove("Dockerfile")


def build_image(path, scenario_name, venv):
    tag_name = tag(scenario_name, venv)
    DOCKER.images.build(path=path, tag=tag_name)
    CONSOLE.print(f"🟢 Image {tag_name} built successfully")


def run_scenario(scenario_name, venv):
    # Flaky :(
    # DOCKER.containers.run(
    #     image=tag(scenario_name, venv),
    #     auto_remove=True,
    #     network="host",
    #     environment=dict(VENV=venv),
    # )
    return subprocess.run(
        f"docker run -v /tmp/results:/results --env VENV={venv} --net=host {tag(scenario_name, venv)}".split(),
        capture_output=True,
    )


@click.command()
@click.argument("scenario")
def main(scenario):
    matrix = get_matrix(scenario)

    scenario_name = matrix["scenario"]["name"]
    CONSOLE.rule(scenario_name)

    venvs = matrix["venvs"]
    py_versions, ddtrace_versions = venvs["python"], venvs["ddtrace"]
    CONSOLE.print(
        f"- Found matrix configuration {{Python: {py_versions}, ddtrace: {ddtrace_versions}}}"
    )

    with CONSOLE.status("Building matrix image ... This may take a while"):
        build_fat_image(scenario_name, py_versions, ddtrace_versions)

    for py, dd in track(
        product(py_versions, ddtrace_versions),
        total=len(py_versions) * len(ddtrace_versions),
        description="Running scenarios",
        console=CONSOLE,
        auto_refresh=False,
        transient=True,
    ):
        venv = f"{py}-{dd}"

        CONSOLE.print(
            f"🛠  Building image for scenario [{scenario_name}] with [Python {py} | ddtrace {dd}]"
        )
        build_image(path=scenario, scenario_name=scenario_name, venv=venv)

        CONSOLE.print(
            f"🏃 Running scenario [{scenario_name}] with [Python {py} | ddtrace {dd}]"
        )
        result = run_scenario(scenario_name=scenario_name, venv=venv)
        CONSOLE.print(result.stdout.decode())

    with CONSOLE.status("📈 Plotting results"):
        plot(py_versions, ddtrace_versions)

    CONSOLE.print("All done! ✨ 🍰 ✨")
