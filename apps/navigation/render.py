"""wp_nav_menu() equivalent: same markup, classes and current-item markers as WordPress."""
from django.core.cache import cache
from django.utils.html import escape

from apps.core.wp_format import wptexturize

from apps.catalog.models import Product

from .models import Menu, MenuItem

TYPE_OBJECT = {
    MenuItem.Target.CUSTOM: ("custom", "custom"),
    MenuItem.Target.PAGE: ("post_type", "page"),
    MenuItem.Target.PRODUCT: ("post_type", "product"),
    MenuItem.Target.POST: ("post_type", "post"),
    MenuItem.Target.PRODUCT_CATEGORY: ("taxonomy", "product_cat"),
    MenuItem.Target.CATEGORY: ("taxonomy", "category"),
}


def _menu_tree(menu_name):
    """Resolved menu as nested dicts; cached because the menu is on every page."""
    key = "navmenu:" + menu_name.replace(" ", "_")
    tree = cache.get(key)
    if tree is not None:
        return tree
    menu = Menu.objects.filter(name=menu_name).first() or Menu.objects.filter(slug=menu_name).first()
    if not menu:
        return []
    items = list(MenuItem.objects.filter(menu=menu).select_related("page", "product_category", "product", "post", "category")
                 .order_by("tree_id", "lft"))
    nvq_ids = [i.product_mmc_nvq_id for i in items if i.product_mmc_nvq_id]
    products = {p.mmc_nvq_id: p for p in Product.objects.filter(mmc_nvq_id__in=nvq_ids, status="publish")}
    nodes = {}
    roots = []
    for item in items:
        resolved = _resolve(item, products)
        if resolved is None:
            continue
        url, title, page_wp_id = resolved
        node = {"id": item.wp_id or item.pk, "title": title, "url": url, "classes": item.css_classes.split(),
                "type": TYPE_OBJECT[item.target_type], "page_id": page_wp_id, "target": item.link_target,
                "children": []}
        nodes[item.pk] = node
        if item.parent_id and item.parent_id in nodes:
            nodes[item.parent_id]["children"].append(node)
        elif not item.parent_id:
            roots.append(node)
    cache.set(key, roots, 300)
    return roots


def clear_menu_cache():
    for menu in Menu.objects.all():
        cache.delete("navmenu:" + menu.name.replace(" ", "_"))
        cache.delete(f"navmenu:{menu.slug}")


def _resolve(item, products):
    t = item.target_type
    if t == MenuItem.Target.PAGE:
        if not item.page or not item.page.is_published:
            return None
        return item.page.get_absolute_url(), item.title or item.page.title, item.page.wp_id or item.page.pk
    if t == MenuItem.Target.PRODUCT:
        product = products.get(item.product_mmc_nvq_id) if item.product_mmc_nvq_id else item.product
        if not product or product.status != "publish":
            return None
        return product.get_absolute_url(), item.title or product.title, None
    if t == MenuItem.Target.PRODUCT_CATEGORY:
        if not item.product_category:
            return None
        return item.product_category.get_absolute_url(), item.title or item.product_category.name, None
    if t == MenuItem.Target.POST:
        if not item.post:
            return None
        return item.post.get_absolute_url(), item.title or item.post.title, None
    if t == MenuItem.Target.CATEGORY:
        if not item.category:
            return None
        return item.category.get_absolute_url(), item.title or item.category.name, None
    return item.url or "#", item.title, None


def _mark_current(nodes, path):
    """Return True if any node in this list (or below) is current; sets flags in place."""
    found = False
    for node in nodes:
        node["current"] = node["url"] not in ("#", "") and node["url"] == path
        child_current = _mark_current(node["children"], path)
        node["parent_of_current"] = any(c["current"] for c in node["children"])
        node["ancestor_of_current"] = child_current
        found = found or node["current"] or child_current
    return found


def _classes(node, has_children):
    item_type, obj = node["type"]
    classes = list(node["classes"]) + ["menu-item", f"menu-item-type-{item_type}", f"menu-item-object-{obj}"]
    if node.get("term_parent"):  # the viewed product is in this menu item's category
        classes += ["current-product-ancestor", "current-menu-parent", "current-product-parent"]
    if node["current"]:
        classes.append("current-menu-item")
        if obj == "page":
            classes += ["page_item", f"page-item-{node['page_id']}", "current_page_item"]
    elif node["ancestor_of_current"]:
        classes.append("current-menu-ancestor")
        if node["parent_of_current"]:
            classes.append("current-menu-parent")
        if obj == "page":
            if node["parent_of_current"]:
                classes.append("current_page_parent")
            classes.append("current_page_ancestor")
    if has_children:
        classes.append("menu-item-has-children")
    classes.append(f"menu-item-{node['id']}")
    return " ".join(classes)


def render_menu(menu_name, path, *, menu_id, menu_class="menu", container="div", container_class=None,
                depth=0, item_ids=True, parent_term_urls=()):
    import copy
    tree = copy.deepcopy(_menu_tree(menu_name))
    _mark_current(tree, path)
    if parent_term_urls:
        def mark_terms(nodes):
            for node in nodes:
                node["term_parent"] = node["type"] == ("taxonomy", "product_cat") and node["url"] in parent_term_urls
                mark_terms(node["children"])
        mark_terms(tree)

    def render_items(nodes, level):
        out = []
        for node in nodes:
            show_children = node["children"] and (depth == 0 or level < depth)
            li_id = f' id="menu-item-{node["id"]}"' if item_ids else ""
            attrs = f' href="{escape(node["url"])}"'
            if node["target"]:
                attrs += f' target="{escape(node["target"])}"'
            if node["current"]:
                attrs += ' aria-current="page"'
            html = f'<li{li_id} class="{_classes(node, bool(show_children))}"><a{attrs}>{wptexturize(node["title"])}</a>'
            if show_children:
                html += '\n<ul class="sub-menu">\n' + render_items(node["children"], level + 1) + "</ul>\n"
            out.append(html + "</li>\n")
        return "".join(out)

    ul = f'<ul id="{menu_id}" class="{menu_class}">' + render_items(tree, 1) + "</ul>"
    if container:
        cls = container_class or f"menu-{_slug(menu_name)}-container"
        return f'<{container} class="{cls}">{ul}</{container}>'
    return ul


def _slug(name):
    return name.lower().replace(" ", "-")
