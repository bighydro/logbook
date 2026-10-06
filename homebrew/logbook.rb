# The Homebrew formula for Logbook: `brew install bighydro/logbook/logbook` once it is published to
# the tap bighydro/homebrew-logbook (homebrew/README.md says how). The formula installs the
# openlogbook release from PyPI into its own virtualenv, with its one runtime dependency as a
# resource, and exposes the `logbook` command. On every release: new url and sha256 here (the
# release checklist, docs/releasing.md), and the ijson resource when PyPI has a newer one.
class Logbook < Formula
  include Language::Python::Virtualenv

  desc "Diary that writes itself: your life, in one folder you hold"
  homepage "https://github.com/bighydro/logbook"
  url "https://files.pythonhosted.org/packages/a8/fe/d8700d09ebe1d850e72b1dc088e65c1513fcadc1f78a1ea5161c5b225c89/openlogbook-0.6.0.tar.gz"
  sha256 "39a0aed9b51cd2000de6915f9603f98dbaf7e716bc4a00f88685ed29d3329c2b"
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
