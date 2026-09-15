{
  description = "Logbook: a diary that writes itself. Your life, in a folder.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      pyproject = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project;
    in
    {
      packages = forEachSystem (
        pkgs:
        let
          python = pkgs.python312;
        in
        {
          # The openlogbook wheel, built the way nixpkgs builds any PEP 517 project.
          default = python.pkgs.buildPythonPackage {
            pname = pyproject.name;
            inherit (pyproject) version;
            pyproject = true;
            src = self;
            build-system = [ python.pkgs.hatchling ];
            dependencies = with python.pkgs; [
              ijson
              tzdata
            ];
            pythonImportsCheck = [ "logbook" ];
            meta = {
              inherit (pyproject) description;
              homepage = "https://github.com/bighydro/logbook";
              license = pkgs.lib.licenses.asl20;
              mainProgram = "logbook";
            };
          };
        }
      );

      devShells = forEachSystem (pkgs: {
        # `nix develop`: Python 3.12 and uv. uv is told to use the Nix interpreter, not download one.
        default = pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.uv
          ];
          env = {
            UV_PYTHON = "${pkgs.python312}/bin/python";
            UV_PYTHON_DOWNLOADS = "never";
          };
        };
      });
    };
}
