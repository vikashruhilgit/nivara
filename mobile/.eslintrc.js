// ESLint config for the Expo SDK 52 mobile app (eslintrc; eslint 8 + eslint-config-expo).
module.exports = {
  root: true,
  extends: 'expo',
  ignorePatterns: ['node_modules/', 'dist/', '.expo/', 'babel.config.js'],
  overrides: [
    {
      files: ['**/*.test.ts', '**/*.test.tsx', '**/__tests__/**', 'jest.setup.js'],
      env: { jest: true },
    },
  ],
};
