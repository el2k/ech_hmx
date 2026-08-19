// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "TGOWidget",
    defaultLocalization: "en",
    platforms: [
        .iOS(.v15)
    ],
    products: [
        .library(name: "TGOWidget", targets: ["TGOWidget"])
    ],
    dependencies: [],
    targets: [
        .target(
            name: "TGOWidget",
            dependencies: [],
            resources: [
                .process("Resources")
            ]
        ),
        .testTarget(
            name: "TGOWidgetTests",
            dependencies: ["TGOWidget"]
        )
    ]
)
