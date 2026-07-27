from typing import Protocol


class MetricsSink(Protocol):
    def increment(self, name: str, value: int = 1) -> None: ...


class NoOpMetricsSink:
    def increment(self, name: str, value: int = 1) -> None:
        pass


def get_metrics_sink() -> MetricsSink:
    return NoOpMetricsSink()
