<?php
/**
 * Renders WordPress content through the_content filters for the Django import.
 * Usage: php wp_render.php <wp-root>   (stdin: JSON array of post IDs)
 * Output: JSON {id: {"content": "<rendered html>"}}
 */
$root = rtrim($argv[1] ?? '', '/');
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REQUEST_URI'] = '/';
define('WP_USE_THEMES', false);
ob_start();
require $root . '/wp-load.php';
ob_end_clean();

$ids = json_decode(stream_get_contents(STDIN), true) ?: array();
$out = array();
foreach ($ids as $id) {
    $post = get_post((int) $id);
    if (!$post) {
        continue;
    }
    $GLOBALS['post'] = $post;
    setup_postdata($post);
    $out[$id] = array('content' => apply_filters('the_content', $post->post_content));
    wp_reset_postdata();
}
echo json_encode($out);
