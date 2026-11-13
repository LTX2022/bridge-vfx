from setuptools import find_packages, setup


setup(
    name="vfx-pipeline",
    version="2.0.0rc1",
    description="Cross-DCC Reference Visual Twin orchestration for Bridge Skills",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=[
        "dcc-task-runtime==2.0.0rc1",
        "houdini-bridge==2.0.0rc1",
        "nuke-bridge==2.0.0rc1",
    ],
    entry_points={"console_scripts": ["vfx-pipeline=vfx_pipeline.__main__:main"]},
)
