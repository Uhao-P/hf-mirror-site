from setuptools import setup, find_packages

setup(
    name="bayes-hub",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "huggingface-hub==0.21.4",
    ],
)
