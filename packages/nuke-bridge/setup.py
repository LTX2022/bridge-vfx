from setuptools import find_packages, setup

setup(
    name="nuke-bridge",
    version="2.0.0rc1",
    description="Local structured Nuke bridge with reference-safe native compositing",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=["dcc-task-runtime==2.0.0rc1"],
    entry_points={"console_scripts": ["nuke-bridge=nuke_bridge.__main__:main"]},
)
