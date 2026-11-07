from setuptools import find_packages, setup

PACKAGE = "bl01_driver"

setup(
    name=PACKAGE,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{PACKAGE}"]),
        (f"share/{PACKAGE}", ["package.xml"]),
        (f"share/{PACKAGE}/launch", ["launch/bl01.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="BL-01 몸 드라이버: 몸(시뮬레이터)의 WebSocket을 ROS 2 토픽·서비스로 낸다",
    license="Proprietary",
    entry_points={"console_scripts": ["driver = bl01_driver.driver_node:main"]},
)
