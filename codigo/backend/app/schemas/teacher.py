from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class GeneralMetrics(BaseModel):
    active_students: int
    retention_pct: float
    queries_today: int


class StudentActivity(BaseModel):
    student_id: str
    full_name: str
    last_topic: Optional[str] = None
    last_session_at: Optional[datetime] = None
    days_with_session_7d: int
    progress_pct: float
    corpus_coverage_pct: float = 0.0


class UnsatisfiedQuery(BaseModel):
    student_name: str
    message: str
    created_at: datetime


class InactiveStudent(BaseModel):
    full_name: str
    days_inactive: Optional[int] = None


class AlertsData(BaseModel):
    unsatisfied_queries: list[UnsatisfiedQuery]
    inactive_students: list[InactiveStudent]


class DocumentMetric(BaseModel):
    filename: str
    display_title: str
    count: int
    top_questions: list[str] = []


class PeakActivityHour(BaseModel):
    hour: int
    message_count: int


class WeeklyActivityPoint(BaseModel):
    week_start: date
    message_count: int


class WeeklyBelowThresholdPoint(BaseModel):
    week_start: date
    ratio_pct: float
    total_queries: int
    below_threshold_queries: int


class ExtendedMetrics(BaseModel):
    avg_queries_per_student: Optional[float] = None
    top_below_threshold_documents: list[DocumentMetric] = []
    peak_activity_hour: Optional[PeakActivityHour] = None
    weekly_activity: list[WeeklyActivityPoint] = []
    top_cited_documents: list[DocumentMetric] = []
    weekly_below_threshold: list[WeeklyBelowThresholdPoint] = []


class StudentBehavior(BaseModel):
    student_id: str
    full_name: str
    avg_queries_per_session: float


class BehaviorInsights(BaseModel):
    deep_students: list[StudentBehavior] = []
    superficial_students: list[StudentBehavior] = []
    followed_up_documents: list[DocumentMetric] = []


class TeacherDashboardResponse(BaseModel):
    metrics: GeneralMetrics
    student_activity: list[StudentActivity]
    alerts: AlertsData
    extended_metrics: ExtendedMetrics
    behavior_insights: BehaviorInsights
