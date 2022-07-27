from setuptools import setup, find_packages
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read()

setup(
    name = 'aws-cfn-nb-extensions',
    version = "0.0.1",
    author = 'Takehiro Horie',
    author_email = 'horie.takehiro@outlook.jp',
    license = 'MIT License',
    description = 'Jupyter notebook extensions for aws cfn.',
    long_description = long_description,
    long_description_content_type = "text/markdown",
    url = 'https://github.com/horietakehiro/aws-cfn-nb-extensions',
    py_modules = ['aws_ext'],
    packages = find_packages(),
    install_requires = [requirements],
    python_requires='>=3.8',
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
    ],
    # entry_points = '''
    #     [console_scripts]
    #     cfn-docgen=main:main
    # '''
)