# The Homebrew formula for Logbook: `brew install bighydro/logbook/logbook` once it is published to
# the tap bighydro/homebrew-logbook (homebrew/README.md says how). The formula installs the
# openlogbook release from PyPI into its own virtualenv, with its one runtime dependency as a
# resource, and exposes the `logbook` command. On every release: new url and sha256 here (the
# release checklist, docs/releasing.md), and the ijson resource when PyPI has a newer one.
class Logbook < Formula
  include Language::Python::Virtualenv

  desc "Diary that writes itself: your life, in one folder you hold"
  homepage "https://github.com/bighydro/logbook"
  url "https://files.pythonhosted.org/packages/81/87/fd3f1fee183efe1e1b51a6f27e5a2a38fa32dfd5d416e40ce07b2309e065/openlogbook-1.2.0.tar.gz"
  sha256 "61149149e83860d46f76464080ff393552728dc04e13a11afd68c82cb31f09bc"
  license "Apache-2.0"
  head "https://github.com/bighydro/logbook.git", branch: "main"

  depends_on "python@3.13"

  resource "ijson" do
    url "https://files.pythonhosted.org/packages/75/61/4066af787ed25bfca02c3edd2d7fd489b1b5ca27b54b400b187e5f2865e7/ijson-3.6.0.tar.gz"
    sha256 "ec8f9265524e724905ecf00bdd061c374baaa8d5045ef50425695fb06efb45f5"
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
