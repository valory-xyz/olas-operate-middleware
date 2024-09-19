<h1 align="center">
<b>Pearl</b>
</h1>

A cross-platform desktop application used to run autonomous agents powered by the OLAS Network.

## Getting Started

### For Users

#### Downloading the latest release

**Note:** The release pages also contain Source Code `.zip` files and `dev-` prefixed builds. These are not intended for general use. Ignore them unless you're a developer!

- Go to the [Releases](https://github.com/valory-xyz/olas-operate-app/releases) page.
- Download the latest release for your operating system.
  - If you're on Windows, download the `.exe` file.
  - If you're on MacOS, download the `.dmg` file.
    - Both Intel x64 and Apple Silicon ARM64 builds are available.
- Install the application by running the downloaded file.

### For Developers

#### Setting up your development environment

- Ubuntu Setup Guide: [docs/dev/ubuntu-setup.md](docs/dev/ubuntu-setup.md)
- MacOS Setup Guide: [docs/dev/macos-setup.md](docs/dev/macos-setup.md)
- Windows Setup Guide: [docs/dev/windows-setup.md](docs/dev/windows-setup.md)

#### Setting up a development RPC endpoint

- RPC Setup Guide: [docs/dev/rpcs.md](docs/dev/rpcs.md)

## Project Dependencies

There are three parts to the project: the Electron app (CommonJS), the NextJS frontend (TypeScript), and the Python backend/middleware.

- Electron dependencies: [package.json](package.json)
- Frontend dependencies: [frontend/package.json](package.json)
- Backend dependencies: [backend/pyproject.toml](backend/pyproject.toml)

## License

- [Apache 2.0](LICENSE)

## Security

- [Security Policy](SECURITY.md)
