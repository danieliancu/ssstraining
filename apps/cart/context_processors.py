def cart(request):
    from .services import cart_count

    if not hasattr(request, "session"):
        return {"cart_count": 0}
    return {"cart_count": cart_count(request)}
