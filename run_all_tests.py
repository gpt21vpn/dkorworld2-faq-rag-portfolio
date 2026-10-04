"""Оба набора тестов базы знаний одной командой: python run_all_tests.py

test_kb.py           — проверки V9/V12 (регрессии приватности, OOS, продолжения диалога)
test_multi_intent.py — формулировки из живого прогона V11 (многосоставные вопросы)
"""
import subprocess
import sys

SUITES = ['test_kb.py', 'test_multi_intent.py']


def main() -> int:
    failed = []
    for suite in SUITES:
        print(f'\n{"=" * 62}\n{suite}\n{"=" * 62}')
        result = subprocess.run([sys.executable, suite], text=True)
        if result.returncode != 0:
            failed.append(suite)
    print('\n' + '=' * 62)
    if failed:
        print('ПРОВАЛЕНО:', ', '.join(failed))
        return 1
    print('Все наборы тестов прошли.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
