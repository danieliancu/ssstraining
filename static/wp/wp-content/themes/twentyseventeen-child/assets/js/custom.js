jQuery(document).ready(function () {

	// adds custom styling to your select menus using bootstrap dropdown.js
	jQuery('select:not(.no-selectpicker)').selectpicker();

	//adds cta class to cf7 to save you the css
	jQuery('.wpcf7-submit').addClass('cta-button');

	// custom styling using div for label and radio elements within CF7
	jQuery("span.wpcf7-form-control-wrap").on('change', 'input[type=checkbox]', function () {
		jQuery(this).parent().toggleClass("highlight");
	});

	jQuery('.wpcf7-radio label').click(function (e) {
		jQuery('.wpcf7-radio label').removeClass("highlight");
		jQuery(this).addClass("highlight");
	});

	// main slider setting )comment out the options you don't need)
	jQuery('.slider-main').slick({
		infinite: true,
		slidesToShow: 1,
		slidesToScroll: 1,
		prevArrow: '<button type="button" class="fa previous fa-chevron-left">',
		nextArrow: '<button type="button" class="fa next fa-chevron-right">',
		dots: true,
		arrows: false,
		autoplay: true,
		fade: true,
	});

	// slick for accreditations-list
	jQuery('.accredications-list-inner').slick({
		infinite: true,
		slidesToShow: 6,
		slidesToScroll: 1,
		prevArrow: '<button type="button" class="fa previous fa-chevron-left general">',
		nextArrow: '<button type="button" class="fa next fa-chevron-right general">',
		dots: false,
		arrows: true,
		responsive: [
			{
				breakpoint: 1200,
				settings: {
					slidesToShow: 6,
					slidesToScroll: 1
				}
			},
			{
				breakpoint: 991,
				settings: {
					slidesToShow: 4,
					slidesToScroll: 1
				}
			},
			{
				breakpoint: 767,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}
			// You can unslick at a given breakpoint now by adding:
			// settings: "unslick"
			// instead of a settings object
		]
	});


	// opens mmobile menu
	jQuery("a#burgerMenu").click(function (e) {
		e.preventDefault();
		jQuery(this).toggleClass('clicked');
		jQuery('.mobile-menu-container').toggleClass('active');
	});

	/* control burger menu sub options */
	jQuery(document).on('click', '.mobile-menu-container li.menu-item-has-children > a', function (e) {
		var $submenu = jQuery(this).next('ul.sub-menu');

		if ($submenu.length && !$submenu.hasClass('active')) {
			e.preventDefault();
			jQuery(this).toggleClass('active');
			$submenu.addClass('active');
		}
	});

	jQuery(document).on('click', '.mobile-menu-container ul.sub-menu a', function () {
		jQuery('.mobile-menu-container').removeClass('active');
		jQuery('#burgerMenu').removeClass('clicked');
		jQuery('.mobile-menu-container li.menu-item-has-children > a').removeClass('active');
		jQuery('.mobile-menu-container ul.sub-menu').removeClass('active');
	});

	//custom scrolling function - use common sense to see how it all fits togehter
	jQuery(".scollingToSection").click(function (e) {
		e.preventDefault();
		var scrollingModule = jQuery(this).attr('data-scrollingModule');
		jQuery('html, body').animate({
			scrollTop: jQuery("#scroll" + scrollingModule).offset().top - 70
		}, 2000);
	});

	/* handles forms + custom loaders */
	/*custom spinner on forms*/
	jQuery(".wpcf7").append('<div class="form-overlay"><div class="loader"></div></div>');

	// Show new spinner on Send button click
	jQuery('.wpcf7-submit').on('click', function () {
		jQuery('.form-overlay').css({ visibility: 'visible' });
	});

	// Hide new spinner on result
	jQuery('div.wpcf7').on('wpcf7invalid wpcf7spam wpcf7mailsent wpcf7mailfailed wpcf7submit', function () {
		jQuery('.form-overlay').css({ visibility: 'hidden' });
	});



});


//Contact Form Request
document.addEventListener('wpcf7mailsent', function (event) {
	//Form Tracking
	ga('gtag_UA_130196588_1.send', 'event', 'Contact', 'submit', 'Contact Request');
}, false);

//Call and phone tracking 
jQuery('a[href^="tel:"]').click(function () {
	ga('gtag_UA_130196588_1.send', 'event', 'Call', 'Click');
});

//Click on email link
jQuery('a[href^="mailto:"]').click(function () {
	ga('gtag_UA_130196588_1.send', 'event', 'Email', 'submit');
});

// Header search modal with live results
(function ($) {
	const ajaxUrl = window.ajaxurl || '/wp-admin/admin-ajax.php';
	const $modal = $('[data-search-modal]');
	const $input = $('[data-search-input]');
	const $results = $('[data-search-results]');
	let timer = null;
	let activeRequest = null;

	if (!$modal.length || !$input.length || !$results.length) {
		return;
	}

	function renderEmpty(message) {
		if (!message) {
			$results.empty();
			return;
		}

		$results.html('<div class="site-search-modal__empty">' + escapeHtml(message) + '</div>');
	}

	function escapeHtml(value) {
		return String(value)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#039;');
	}

	function openModal() {
		$modal.addClass('is-open').attr('aria-hidden', 'false');
		$('body').addClass('site-search-open');
		setTimeout(function () {
			$input.trigger('focus');
		}, 50);
	}

	function closeModal() {
		$modal.removeClass('is-open').attr('aria-hidden', 'true');
		$('body').removeClass('site-search-open');
	}

	function renderResults(items) {
		if (!items || !items.length) {
			renderEmpty('No results found.');
			return;
		}

		const html = items.map(function (item) {
			let titleLine = escapeHtml(item.title);
			if (item.is_product && item.compact_date) {
				titleLine += ' | ' + escapeHtml(item.compact_date);
			}

			let detailsHtml = '';
			if (item.is_product && item.details && item.details.length) {
				detailsHtml = '<div class="site-search-modal__product-details">' + item.details.map(function (detail) {
					return '<div class="site-search-modal__product-detail"><span class="site-search-modal__product-detail-label">' + escapeHtml(detail.label) + ':</span> <span class="site-search-modal__product-detail-value">' + escapeHtml(detail.value) + '</span></div>';
				}).join('') + '</div>';
			}

			return (
				'<a class="site-search-modal__result" href="' + escapeHtml(item.url) + '">' +
				'<span class="site-search-modal__result-title">' + titleLine + '</span>' +
				(detailsHtml || '<span class="site-search-modal__result-type">' + escapeHtml(item.type) + '</span>') +
				'</a>'
			);
		}).join('');

		$results.html(html);
	}

	function fetchResults(term) {
		if (activeRequest && activeRequest.readyState !== 4) {
			activeRequest.abort();
		}

		if (!term || term.length < 2) {
			renderEmpty('');
			return;
		}

		$results.html('<div class="site-search-modal__loading">Searching...</div>');

		activeRequest = $.ajax({
			url: ajaxUrl,
			method: 'POST',
			dataType: 'json',
			data: {
				action: 'sst_search_modal',
				term: term
			}
		}).done(function (response) {
			if (response && response.success && response.data) {
				renderResults(response.data.results || []);
			} else {
				renderEmpty('No results found.');
			}
		}).fail(function () {
			renderEmpty('Search is temporarily unavailable.');
		});
	}

	$(document).on('click', '[data-search-open]', function (event) {
		event.preventDefault();
		openModal();
		fetchResults($input.val().trim());
	});

	$(document).on('click', '[data-search-close]', function (event) {
		event.preventDefault();
		closeModal();
	});

	$(document).on('keydown', function (event) {
		if (event.key === 'Escape') {
			closeModal();
		}
	});

	$input.on('input', function () {
		const term = $(this).val().trim();
		clearTimeout(timer);
		timer = setTimeout(function () {
			fetchResults(term);
		}, 250);
	});

	$modal.find('.site-search-modal__form').on('submit', function () {
		closeModal();
	});

	renderEmpty('');
})(jQuery);


// acc with minmum fuss, please maintain html layout from example
if (jQuery(".acc-title").length) {
	jQuery(".acc-title").click(function (event) {
		event.preventDefault();
		jQuery(this).parent().children('.acc-title').toggleClass('active');
		jQuery(this).parent().children('.acc-section').slideToggle();
	});
}
// Tab switching functionality from body.html
document.querySelectorAll('.tab-btn').forEach(btn => {
	btn.addEventListener('click', function () {
		const tabName = this.getAttribute('data-tab');

		// Remove active class from all tabs and buttons
		document.querySelectorAll('.tab-btn').forEach(b => {
			b.classList.remove('active');
			b.style.background = '#f1f4f8';
			b.style.color = '#0a1f44';
			b.style.borderBottomColor = 'transparent';
		});

		document.querySelectorAll('.tab-content').forEach(content => {
			content.classList.remove('active');
			content.style.display = 'none';
		});

		// Add active class to clicked button and corresponding content
		this.classList.add('active');
		this.style.background = '#0a1f44';
		this.style.color = 'white';
		this.style.borderBottomColor = '#0066ff';

		const activeContent = document.getElementById(tabName + '-tab');
		activeContent.classList.add('active');
		activeContent.style.display = 'block';
	});
});
