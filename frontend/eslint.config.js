import tseslint from 'typescript-eslint';
export default tseslint.config(...tseslint.configs.recommended, {
  files: ['**/*.ts', '**/*.tsx'],
  languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
});
