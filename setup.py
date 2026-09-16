from setuptools import setup, find_packages

setup(
    name="smalilog",
    version="0.1.0",
    description="Herramienta CLI para inyección Smali y registro remoto de logs en Android",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="1jehuang",
    url="https://github.com/1jehuang/smalilog",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "websockets>=12",
    ],
    entry_points={
        "console_scripts": [
            "smalilog=smalilog.main:cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Operating System :: Android",
        "Programming Language :: Python :: 3",
        "Topic :: Utilities",
    ],
)
