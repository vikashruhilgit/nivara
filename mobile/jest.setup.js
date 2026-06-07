/**
 * Jest setup — registers native-module mocks needed for the JSDOM/node test env.
 */

// Official AsyncStorage mock (the native module is null under Jest).
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
