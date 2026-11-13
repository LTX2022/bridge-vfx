from setuptools import find_packages, setup

setup(
    name="dcc-task-runtime",
    version="2.0.0rc1",
    description="Durable causal VFX task, approval, evidence, and artifact primitives",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
)
