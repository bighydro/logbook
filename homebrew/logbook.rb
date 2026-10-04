# The Homebrew formula for Logbook: `brew install bighydro/logbook/logbook` once it is published to
# the tap bighydro/homebrew-logbook (homebrew/README.md says how). The formula installs the
# openlogbook release from PyPI into its own virtualenv, with its one runtime dependency as a
# resource, and exposes the `logbook` command. On every release: new url and sha256 here (the
# release checklist, docs/releasing.md), and the ijson resource when PyPI has a newer one.
class Logbook < Formula
  include Language::Python::Virtualenv

  desc "Diary that writes itself: your life, in one folder you hold"
  homepage "https://github.com/bighydro/logbook"
  url "https://files.pythonhosted.org/packages/ae/a8/af5ded23e9c5e0b9d4897d04834f3e5baa9c8693bc41b634452abf896550/openlogbook-0.5.0.tar.gz"
  sha256 "d2fd8dcccf48a20e75a752818ae82d47c9870ec0d69fb212f77e6f229333e9e7"
  license "Apache-2.0"
  head "https://github.com/bighydro/logbook.git", branch: "main"

  depends_on "python@3.13"

  resource "ijson" do
    url "https://files.pythonhosted.org/packages/3a/06/b31f040a8764336a11152e474a7abcb3782fedb0d1cdf78f442b82878c56/ijson-3.5.1.tar.gz"
    sha256 "af40bd1a85f55db0b8b30715c858761306bd92d5590148636f75c3309e6e76bd"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/logbook --version")
    # A record of one invented sentence, written and read back; nothing of the tester's. Only
    # commands every release has had (init, add, verify), so the block outlives the pinned version.
    record = testpath/"Logbook"
    system bin/"logbook", "init", record, "--timezone", "Europe/Oslo"
    ENV["LOGBOOK_HOME"] = record.to_s
    system bin/"logbook", "add", "had lunch with a friend by the lake"
    assert_match "valid", shell_output("#{bin}/logbook verify --root #{record}")
  end
end
