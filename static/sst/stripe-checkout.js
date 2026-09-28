/**
 * Stripe Payment Element for the WooCommerce checkout form (replaces the WC Stripe gateway JS).
 *
 * - Mounts the Payment Element (accordion layout) in #wc-stripe-upe-form .wc-stripe-upe-element,
 *   re-mounting after WooCommerce replaces the payment fragment (updated_checkout).
 * - On "Place order" (checkout_place_order_stripe) it validates the element, creates a
 *   ConfirmationToken, stores it in #sst_stripe_confirmation_token and resubmits the form.
 * - When the server answers with redirect "#sst-stripe-confirm:<client_secret>:<return url>"
 *   (3-D Secure etc.) it runs stripe.handleNextAction() and then goes to the order-received page.
 */
(function ($) {
    'use strict';
    if (!window.Stripe || !window.sstStripe || !window.sstStripe.key) {
        return;
    }
    var stripe = window.Stripe(window.sstStripe.key);
    var elements = null;
    var paymentElement = null;
    var tokenReady = false;
    var $form = $('form.checkout');

    function amountInPence() {
        var text = $('.order-total .woocommerce-Price-amount').last().text().replace(/[^0-9.]/g, '');
        var value = parseFloat(text || window.sstStripe.amount || '0');
        return Math.max(30, Math.round(value * 100));
    }

    function mount() {
        var $slot = $('#wc-stripe-upe-form .wc-stripe-upe-element');
        if (!$slot.length) {
            return;
        }
        if (!elements) {
            elements = stripe.elements({
                mode: 'payment',
                amount: amountInPence(),
                currency: window.sstStripe.currency || 'gbp',
                paymentMethodCreation: 'manual',
                appearance: { theme: 'stripe', variables: { fontFamily: 'Poppins, Arial, sans-serif', borderRadius: '4px' } }
            });
            paymentElement = elements.create('payment', { layout: { type: 'accordion', defaultCollapsed: false } });
        } else {
            elements.update({ amount: amountInPence() });
        }
        if (!$slot.children().length) {
            paymentElement.mount($slot[0]);
        }
    }

    function showError(message) {
        $('#wc-stripe-upe-errors').html('<ul class="woocommerce-error"><li>' + $('<div>').text(message).html() + '</li></ul>');
        $form.removeClass('processing').unblock();
    }

    $(document.body).on('updated_checkout', function () {
        tokenReady = false;
        mount();
    });

    $form.on('checkout_place_order_stripe', function () {
        if (tokenReady) {
            tokenReady = false;
            return true;
        }
        if (!elements) {
            return true;
        }
        elements.submit().then(function (result) {
            if (result.error) {
                showError(result.error.message);
                return null;
            }
            return stripe.createConfirmationToken({
                elements: elements,
                params: {
                    billing_details: {
                        name: ($('#billing_first_name').val() + ' ' + $('#billing_last_name').val()).trim(),
                        email: $('#billing_email').val(),
                        phone: $('#billing_phone').val() || null,
                        address: {
                            line1: $('#billing_address_1').val(),
                            line2: $('#billing_address_2').val() || null,
                            city: $('#billing_city').val(),
                            state: $('#billing_state').val() || null,
                            postal_code: $('#billing_postcode').val(),
                            country: $('#billing_country').val() || 'GB'
                        }
                    }
                }
            });
        }).then(function (result) {
            if (!result) {
                return;
            }
            if (result.error) {
                showError(result.error.message);
                return;
            }
            $('#sst_stripe_confirmation_token').val(result.confirmationToken.id);
            tokenReady = true;
            $form.trigger('submit');
        });
        return false;
    });

    function handleHash() {
        var match = window.location.hash.match(/^#sst-stripe-confirm:([^:]+):(.+)$/);
        if (!match) {
            return;
        }
        var clientSecret = match[1];
        var returnUrl = decodeURIComponent(match[2]);
        history.replaceState(null, '', window.location.pathname + window.location.search);
        stripe.handleNextAction({ clientSecret: clientSecret }).then(function (result) {
            if (result.error) {
                showError(result.error.message);
                $('#sst_stripe_confirmation_token').val('');
                return;
            }
            window.location = returnUrl;
        });
    }

    window.addEventListener('hashchange', handleHash);
    $(function () {
        mount();
        handleHash();
    });
})(jQuery);
