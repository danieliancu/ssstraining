#!/bin/sh
# Captures reference HTML from the local WordPress clone.
BASE=${WP_BASE:-http://localhost/sst}
OUT=$(dirname "$0")/golden
mkdir -p "$OUT"
while read -r name path; do
  [ -z "$name" ] && continue
  curl -s -L "$BASE$path" -o "$OUT/$name.html"
  echo "$name $(wc -c < "$OUT/$name.html")"
done <<LIST
home /
shop /shop/
shop_filtered /shop/?course_ref=smsts
cat_smsts /product-category/smsts/
cat_nvq /product-category/nvq/
product_session /product/site-management-safety-training-scheme-03-10-2026/
product_nvq /product/level-7-senior-site-management/
nvq_level2 /level-2-nvqs/
nebosh_dl /nebosh-distance-learning/
fire_safety /certificate-in-fire-safety/
env_mgmt /environmental-management-certificate/
contact /contact-us/
privacy /privacy-policy/
cookie /cookie-policy/
ssip /nebosh-tutoring/
blog /blog/
post /blog/smsts-online-vs-classroom/
category /uncategorised/
author /blog/author/daniel/
news_archive /blog/news/
news_single /blog/news/nebosh-course-offers/
news_cat /blog/news-category/news/
nebosh_archive /blog/nebosh_course/
nebosh_single /blog/nebosh_course/nebosh-general-certificate/
safety_archive /blog/safety_course/
safety_single /blog/safety_course/site-manager-safety-training-scheme-smsts/
search /?s=smsts
notfound /this-page-does-not-exist/
basket_empty /basket/
robots /robots.txt
sitemap_index /sitemap_index.xml
sitemap_page /page-sitemap.xml
sitemap_post /post-sitemap.xml
LIST
# Stateful: basket with items and checkout
JAR=$(mktemp)
curl -s -c "$JAR" -b "$JAR" -L "$BASE/?add-to-cart=2823&quantity=2" -o /dev/null
curl -s -c "$JAR" -b "$JAR" -L "$BASE/basket/" -o "$OUT/basket_full.html"
curl -s -c "$JAR" -b "$JAR" -L "$BASE/checkout-2/" -o "$OUT/checkout.html"
echo "basket_full $(wc -c < "$OUT/basket_full.html")"; echo "checkout $(wc -c < "$OUT/checkout.html")"
rm -f "$JAR"
