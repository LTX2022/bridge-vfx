from setuptools import find_packages, setup

setup(
    name="houdini-bridge",
    version="2.0.0rc1",
    description="Local structured Houdini bridge with editable VFX domain adapters",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=["dcc-task-runtime==2.0.0rc1"],
    entry_points={"console_scripts": ["houdini-bridge=houdini_bridge.__main__:main"]},
)
