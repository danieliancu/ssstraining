from apps.blog.views import get_visible, render_single

from .models import ExamPaper


def detail(request, slug):
    """single.php for the sst_exam_paper post type (/blog/exam-paper/<slug>/)."""
    paper = get_visible(request, ExamPaper, slug=slug)
    return render_single(request, paper, "sst_exam_paper")
