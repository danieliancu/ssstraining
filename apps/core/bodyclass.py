"""WordPress body_class() output for each page type. The theme CSS keys off these classes."""

THEME = "wp-embed-responsive wp-theme-twentyseventeen wp-child-theme-twentyseventeen-child theme-twentyseventeen"

# _wp_page_template value → template class stem, as WP derives it from the file path.
TEMPLATE_FILES = {
    "front": "page-templates/front-page.php",
    "page_only": "page-only.php",
    "api": "page-api.php",
    "nvq_level": "page-templates/nvq-level-page.php",
    "nebosh_dl": "page-templates/nebosh-distance-learning.php",
    "category": "page-templates/category-page.php",
}


def _template_classes(file):
    """page-template page-template-page-templates page-template-front-page page-template-page-templatesfront-page-php"""
    parts = file.replace(".php", "").split("/")
    classes = ["page-template"] + [f"page-template-{p}" for p in parts]
    classes.append("page-template-" + file.replace("/", "").replace(".", "-"))
    return classes


def _tail(woo=(), hfeed=False, two_column=True, front=False):
    classes = [THEME, *woo, "woocommerce-no-js"]
    if front:
        classes.append("twentyseventeen-front-page")
    if hfeed:
        classes.append("hfeed")
    classes.append("has-header-image")
    if two_column:
        classes.append("page-two-column")
    classes.append("colors-light")
    return classes


def page_classes(page, woo=(), template_override=None):
    classes = []
    if page.is_front_page:
        classes.append("home")
    classes.append("wp-singular")
    template_key = template_override or page.template
    if template_key == "page_only" and page.slug == "certificate-in-fire-safety":
        template_key = "api"  # WP reports the meta template although page-only.php renders
    if template_key in TEMPLATE_FILES:
        classes += _template_classes(TEMPLATE_FILES[template_key])
    else:
        classes.append("page-template-default")
    classes += ["page", f"page-id-{page.wp_id or page.pk}"]
    return " ".join(classes + _tail(woo=woo, front=page.is_front_page))


def single_classes(obj, post_type, woo=(), format_standard=True):
    classes = ["wp-singular", f"{post_type}-template-default", "single", f"single-{post_type}", f"postid-{obj.wp_id or obj.pk}"]
    if format_standard:
        classes.append("single-format-standard")
    return " ".join(classes + _tail(woo=woo, two_column=False))


def archive_classes(extra, woo=(), two_column=True):
    return " ".join(["archive", *extra] + _tail(woo=woo, hfeed=True, two_column=two_column))


def blog_classes():
    return " ".join(["blog"] + _tail(hfeed=True, two_column=False))


def search_classes(has_results=True):
    return " ".join(["search", "search-results" if has_results else "search-no-results"] + _tail(hfeed=True, two_column=False))


def error404_classes():
    return " ".join(["error404"] + _tail(hfeed=True, two_column=False))
