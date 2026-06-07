// Metro configuration for InvestIQ.
//
// We disable Watchman on purpose. This repo lives under ~/Documents, which
// macOS TCC (privacy) protects, and the Homebrew `watchman` binary is denied
// access to it — `realpath(...) -> Operation not permitted` — which crashes
// `expo start`. Forcing Metro's built-in node filesystem crawler
// (resolver.useWatchman = false) sidesteps Watchman entirely, so the bundler
// starts cleanly without needing Full Disk Access or moving the repo.
//
// Trade-off: the node crawler is a little slower at detecting file changes
// than Watchman on very large trees; for this project it's a non-issue.
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

config.resolver.useWatchman = false;

module.exports = config;
