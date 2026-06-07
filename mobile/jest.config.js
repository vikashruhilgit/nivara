/**
 * Jest config for the InvestIQ mobile app.
 *
 * Uses the `jest-expo` preset (SDK 52). The transformIgnorePatterns allow the
 * RN / Expo / svg / blur / async-storage ESM packages through Babel so they can
 * be transformed (the standard jest-expo allow-list).
 */
module.exports = {
  preset: 'jest-expo',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@unimodules/.*|unimodules|sentry-expo|native-base|react-native-svg|@react-native-async-storage/.*))',
  ],
};
