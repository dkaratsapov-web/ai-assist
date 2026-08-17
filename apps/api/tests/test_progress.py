"""Прогресс проекта по десяти шагам (v0.4 §3).

Проверяется главным образом одно свойство: шаг не отмечается сделанным, пока
для него нет данных. Нарисованный прогресс хуже пустого — по нему принимают
решения о том, что делать дальше.
"""

from __future__ import annotations

from ads_os.services.economics import EconomicsMode
from ads_os.services.progress import (
    ProgressInput,
    StepKey,
    StepState,
    evaluate,
)


def state(data: ProgressInput, key: StepKey) -> StepState:
    return next(s.state for s in evaluate(data).steps if s.key is key)


def hint(data: ProgressInput, key: StepKey) -> str | None:
    return next(s.hint for s in evaluate(data).steps if s.key is key)


class TestСоставШагов:
    def test_шагов_ровно_десять(self) -> None:
        """Канонический цикл один и не расходится по разделам."""
        assert len(evaluate(ProgressInput()).steps) == 10

    def test_порядок_шагов_фиксирован(self) -> None:
        keys = [s.key for s in evaluate(ProgressInput()).steps]
        assert keys == list(StepKey)

    def test_все_шаги_подписаны(self) -> None:
        assert all(s.label for s in evaluate(ProgressInput()).steps)


class TestНовыйПроект:
    def test_онбординг_не_закрывается_фактом_создания(self) -> None:
        """Иначе человек ввёл название и уже «один шаг из десяти».

        Формальность, оформленная как достижение, — та же выдуманная цифра,
        только в виде галочки.
        """
        assert state(ProgressInput(), StepKey.ONBOARDING) is StepState.ACTIVE

    def test_ничего_не_сделано(self) -> None:
        assert evaluate(ProgressInput()).completed_count == 0

    def test_текущий_шаг_онбординг(self) -> None:
        """Первое осмысленное действие — заполнить сайт и нишу."""
        assert evaluate(ProgressInput()).current is StepKey.ONBOARDING

    def test_видно_чего_именно_не_хватает(self) -> None:
        hint = evaluate(ProgressInput()).steps[0].hint or ""

        assert "сайт" in hint and "ниш" in hint

    def test_сайт_и_ниша_закрывают_онбординг(self) -> None:
        data = ProgressInput(has_website=True, has_niche=True)

        assert state(data, StepKey.ONBOARDING) is StepState.COMPLETED

    def test_только_сайта_мало(self) -> None:
        data = ProgressInput(has_website=True)

        assert state(data, StepKey.ONBOARDING) is StepState.ACTIVE
        assert "ниш" in (evaluate(data).steps[0].hint or "")

    def test_проект_без_сайта_не_блокируется(self) -> None:
        """Реклама без сайта бывает — на квизы, на карточки в справочниках.
        Запретить такой проект нельзя, промолчать о том, что исследовать
        нечего, — тоже."""
        data = ProgressInput(has_niche=True)

        assert state(data, StepKey.ONBOARDING) is not StepState.BLOCKED
        assert "сайт" in (evaluate(data).steps[0].hint or "")

    def test_есть_подсказка_что_делать(self) -> None:
        assert evaluate(ProgressInput()).next_action


class TestИсследование:
    def test_без_сайта_шаг_требует_действия(self) -> None:
        """Состояние «ожидает» означало бы, что ждём мы. Здесь ждём пользователя."""
        data = ProgressInput(has_website=False)
        assert state(data, StepKey.RESEARCH) is StepState.ACTIVE
        assert "адрес сайта" in (hint(data, StepKey.RESEARCH) or "")

    def test_сайт_есть_а_проверки_не_было(self) -> None:
        data = ProgressInput(has_website=True)
        assert state(data, StepKey.RESEARCH) is StepState.ACTIVE
        assert hint(data, StepKey.RESEARCH) == "Запустите проверку сайта"

    def test_проверка_идёт(self) -> None:
        data = ProgressInput(has_website=True, audit_status="running")
        assert state(data, StepKey.RESEARCH) is StepState.ACTIVE

    def test_один_аудит_не_закрывает_исследование(self) -> None:
        """Исследование — это аудит и конкуренты (v0.4 §3)."""
        data = ProgressInput(has_website=True, audit_status="completed")
        assert state(data, StepKey.RESEARCH) is StepState.ACTIVE
        assert "конкурент" in (hint(data, StepKey.RESEARCH) or "")

    def test_аудит_и_конкуренты_закрывают_исследование(self) -> None:
        data = ProgressInput(has_website=True, audit_status="completed", competitors_checked=2)
        assert state(data, StepKey.RESEARCH) is StepState.COMPLETED

    def test_критические_находки_не_отменяют_исследования(self) -> None:
        """Исследование выполнено. Запуск блокирует отдельный шаг, не этот."""
        data = ProgressInput(
            has_website=True,
            audit_status="completed",
            audit_has_blocking_issues=True,
            competitors_checked=1,
        )
        assert state(data, StepKey.RESEARCH) is StepState.COMPLETED

    def test_неудачная_проверка_это_ошибка_а_не_ожидание(self) -> None:
        """Разница важна: ошибку чинят, ожидание пережидают."""
        data = ProgressInput(has_website=True, audit_status="failed")
        assert state(data, StepKey.RESEARCH) is StepState.ERROR


class TestЭкономика:
    def test_пустая_экономика_требует_действия(self) -> None:
        data = ProgressInput(economics_mode=EconomicsMode.INSUFFICIENT)
        assert state(data, StepKey.ECONOMICS) is StepState.ACTIVE
        assert "бюджет" in (hint(data, StepKey.ECONOMICS) or "")

    def test_частичная_экономика_не_считается_готовой(self) -> None:
        """Ограниченный режим — рабочее состояние, но не завершённый шаг."""
        data = ProgressInput(economics_mode=EconomicsMode.LIMITED)
        assert state(data, StepKey.ECONOMICS) is StepState.ACTIVE

    def test_полная_экономика_завершает_шаг(self) -> None:
        data = ProgressInput(economics_mode=EconomicsMode.COMPLETE)
        assert state(data, StepKey.ECONOMICS) is StepState.COMPLETED


class TestЗапуск:
    def test_без_кабинета_запуск_заблокирован(self) -> None:
        data = ProgressInput(ad_account_connected=False)
        assert state(data, StepKey.LAUNCH) is StepState.BLOCKED

    def test_критические_находки_блокируют_запуск(self) -> None:
        """Прямое требование v0.3 §15."""
        data = ProgressInput(
            has_website=True,
            audit_status="completed",
            audit_has_blocking_issues=True,
            ad_account_connected=True,
        )
        assert state(data, StepKey.LAUNCH) is StepState.BLOCKED
        assert "критические" in (hint(data, StepKey.LAUNCH) or "")

    def test_причина_блокировки_названа(self) -> None:
        """Заблокированный шаг без объяснения бесполезен."""
        assert hint(ProgressInput(), StepKey.LAUNCH)


class TestТекущийШаг:
    def test_ошибка_важнее_незаполненности(self) -> None:
        """Сломанное чинят раньше, чем заполняют следующее."""
        data = ProgressInput(
            has_website=True,
            has_niche=True,
            audit_status="failed",
            economics_mode=EconomicsMode.INSUFFICIENT,
        )
        assert evaluate(data).current is StepKey.RESEARCH

    def test_после_исследования_текущей_становится_экономика(self) -> None:
        data = ProgressInput(
            has_website=True,
            has_niche=True,
            audit_status="completed",
            competitors_checked=1,
            economics_mode=EconomicsMode.INSUFFICIENT,
        )
        assert evaluate(data).current is StepKey.ECONOMICS

    def test_подсказка_относится_к_текущему_шагу(self) -> None:
        data = ProgressInput(
            has_website=True, competitors_checked=1, economics_mode=EconomicsMode.COMPLETE
        )
        progress = evaluate(data)
        current = next(s for s in progress.steps if s.key is progress.current)
        assert progress.next_action == current.hint


class TestСборкаКампании:
    """Шаги «Стратегия» и «Сборка» перестали быть заглушками."""

    def test_готовая_стратегия_закрывает_шаг(self) -> None:
        progress = evaluate(
            ProgressInput(
                has_website=True,
                audit_status="completed",
                competitors_checked=2,
                economics_mode=EconomicsMode.COMPLETE,
                strategy_ready=True,
            )
        )

        strategy = next(s for s in progress.steps if s.key is StepKey.STRATEGY)
        assert strategy.state is StepState.COMPLETED

    def test_без_фраз_сборка_ждёт_действия(self) -> None:
        progress = evaluate(
            ProgressInput(
                has_website=True,
                audit_status="completed",
                competitors_checked=2,
                economics_mode=EconomicsMode.COMPLETE,
                strategy_ready=True,
            )
        )

        build = next(s for s in progress.steps if s.key is StepKey.BUILD)
        assert build.state is StepState.ACTIVE
        assert build.hint is not None and "фраз" in build.hint

    def test_фразы_без_объявлений_шаг_не_закрывают(self) -> None:
        """Список фраз сам по себе — ещё не кампания."""
        progress = evaluate(
            ProgressInput(
                has_website=True,
                audit_status="completed",
                competitors_checked=2,
                economics_mode=EconomicsMode.COMPLETE,
                strategy_ready=True,
                keywords_count=120,
                clusters_count=6,
                ad_drafts_ready=0,
            )
        )

        build = next(s for s in progress.steps if s.key is StepKey.BUILD)
        assert build.state is StepState.ACTIVE
        assert build.hint is not None and "Директа" in build.hint

    def test_готовые_объявления_закрывают_сборку(self) -> None:
        progress = evaluate(
            ProgressInput(
                has_website=True,
                audit_status="completed",
                competitors_checked=2,
                economics_mode=EconomicsMode.COMPLETE,
                strategy_ready=True,
                keywords_count=120,
                clusters_count=6,
                ad_drafts_ready=6,
            )
        )

        build = next(s for s in progress.steps if s.key is StepKey.BUILD)
        assert build.state is StepState.COMPLETED

    def test_без_стратегии_сборка_ждёт_её(self) -> None:
        progress = evaluate(
            ProgressInput(has_website=True, audit_status="completed", competitors_checked=1)
        )

        build = next(s for s in progress.steps if s.key is StepKey.BUILD)
        assert build.state is StepState.WAITING
