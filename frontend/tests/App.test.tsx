// @vitest-environment jsdom
import { afterEach, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App } from '../src/App';
afterEach(cleanup);
test('identifica la página técnica sin ofrecer diagnóstico o carga', () => {
  const { container } = render(<App />);
  expect(screen.getByRole('heading', { name: 'Entorno técnico' })).toBeVisible();
  expect(screen.getByText(/diagnóstico de cultivos todavía no está disponible/)).toBeVisible();
  expect(container.querySelector('input[type=file]')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
});
