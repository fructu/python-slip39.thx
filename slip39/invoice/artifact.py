
#
# Python-slip39 -- Ethereum SLIP-39 Account Generation and Recovery
#
# Copyright (c) 2022, Dominion Research & Development Corp.
#
# Python-slip39 is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.  It is also available under alternative (eg. Commercial) licenses, at
# your option.  See the LICENSE file at the top of the source tree.
#
# Python-slip39 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
from __future__          import annotations

import logging
import math
import json

from dataclasses	import dataclass
from collections	import namedtuple, defaultdict
from typing		import Dict, Union, Optional, Sequence, List, Any
from fractions		import Fraction
from pathlib		import Path
from datetime		import datetime, timedelta, timezone
from calendar		import monthrange

import fpdf

from tabulate		import tabulate
from crypto_licensing.misc import get_localzone

from ..api		import Account
from ..util		import commas, is_listlike, is_mapping
from ..defaults		import INVOICE_CURRENCY, INVOICE_ROWS, INVOICE_STRFTIME, INVOICE_DUE, MM_IN, FILENAME_FORMAT
from ..layout		import Region, Text, Image, Box, Coordinate, layout_pdf
from .ethereum		import tokeninfo, tokenprices, TokenInfo  # , tokenratio

"""
Invoice artifacts:

    Invoice/Quote	-- States deliverables, prices/taxes, and totals in various currencies

    Receipt		-- The Invoice, marked "PAID"


"""
log				= logging.getLogger( "customer" )


# An invoice line-Item contains the details of a component of a transaction.  It is priced in a
# currency, with a number of 'units', and a 'price' per unit.
#
# The 'tax' is a proportion of the computed total amount allocated to taxation; if <1 (eg. 0.05 or
# 5%), then it is added to the total amount; if > 1 (eg. 1.05 or 5%), then the prices is assumed to
# be tax-inclusive and it is subtracted from the computed amount.
#
# Each line-Item may be expressed in a different currency.
Item				= namedtuple( 'Item', [
    'description',			# "Widgets for The Thing"
    'units',				# 198
    'price',				# 1.98 eg. $USD, Fraction( 10000, 12 ) * 10**9, eg. ETH Gwei per dozen, in Wei
    'tax',				# 0.05, Fraction( 5, 100 ) eg. GST, added to amount, 1.05 GST, included in amount
    'decimals',				# Number of decimals to display computed amounts, eg. 2.  Default: currency's decimals//3
    'currency'				# USD
] )


@dataclass
class Item:
    description: str				# "Widgets for The Thing"
    price: Union[int,float,Fraction]		# 1.98 eg. $USDC, Fraction( 10000, 12 ) * 10**9, eg. ETH Gwei per dozen, in Wei
    units: Union[int,float]	= 1		# 198, 1.5
    tax: Optional[float,Fraction] = None        # 0.05, Fraction( 5, 100 ) eg. GST, added to amount, 1.05 GST, included in amount
    decimals: Optional[int]	= None		# Number of decimals to display computed amounts, eg. 2.; default is 1/3 of token decimals
    currency: Optional[str]	= None		# Default: $USD (value proxy is USDC)


class LineItem( Item ):
    def net( self ):
        """Computes the LineItem total 'amount', the 'taxes', and info on tax charged.

        Uses the default Invoice Currency if none specified.

        """
        amount			= self.units * self.price
        taxes			= 0
        taxinf			= 'no tax'
        if self.tax:
            if self.tax < 1:
                taxinf		= f"{round( float( self.tax * 100 ), 2):g}% added"
                taxes		= amount * self.tax
                amount	       += taxes
            elif self.tax > 1:
                taxinf		= f"{round( float(( self.tax - 1 ) * 100 ), 2):g}% incl."
                taxes		= amount - amount / self.tax
        return amount, taxes, taxinf  # denominated in self.currencies


def conversions_table( conversions, symbols=None ):
    if symbols is None:
        symbols			= sorted( set( sum( conversions.keys(), () )))
    symbols			= list( symbols )

    # The columns are typed according to the least generic type that *all* rows are convertible
    # into.  So, if any row is a string, it'll cause the entire column to be formatted as strings.
    return tabulate(
        [
            [ r ] + list(
                1 if r == c else '' if (r,c) not in conversions else conversions.get( (r,c) )
                for c in symbols
            )
            for r in symbols
        ],
        headers		= [ 'Symbol' ] + list( symbols ),
        floatfmt	= ",.6g",
        intfmt		= ",",
        missingval	= "?",
        tablefmt	= 'orgtbl',
    )


def conversions_remaining( conversions, verify=None ):
    """Complete the graph of conversion ratios, if we have a path from one pair to another.  Returns
    falsey if no additional conversion ratios were computable; truthy if some *might* be possible.
    Each run looks for single-hop conversions available.

    Put any desired conversions (eg. DOGE/USD) into conversions w/ None as value.

    For example, if ETH/USD: 1234.56 and BTC/USD: 23456.78, then we can deduce BTC/ETH:
    19.0001134007 and ETH/BTC: 0.05263126482.  Then, on the next call, we could compute DOGE/USD ==
    0.090308 if we provide BTC/DOGE: 3.85e-6

    Updates the supplied { ('a','b'): <ratio>, ...} dict, in-place.

    If NO None values remain after all computable ratios are deduced, returns False, meaning "no remaining unresolved conversions".

    Otherwise, return None iff we couldn't deduce any more conversion ratios, but there remain some
    unresolved { (a,b): None, ...} in conversions.

    """
    updated			= False
    # First, take care of any directly available one-hop conversions.
    for (a,b),r in list( conversions.items() ):
        if r and conversions.get( (b,a) ) is None:
            conversions[b,a]	= 1/r
            log.info( f"Deduced {b:>6}/{a:<6} = {float( 1/r ):13.6f} from {a:>6}/{b:<6} == {float( r ):13.6f} == {r}" )
            updated		= True
        if r is None:
            continue
        for (a2,b2),r2 in list( conversions.items() ):
            if r2 is None:
                continue
            if b == a2 and a != b2 and conversions.get( (a,b2) ) is None:
                # Eg. USD/BTC=25000/1 * BTC/DOGE=1/275000 --> USD/DOGE=1/4
                conversions[a,b2] = r * r2
                log.info( f"Invert  {a:>6}/{b2:<6} = {float( conversions[a,b2] ):13.6f} from {a:>6}/{b:<6} == {float( r ):13.6f} and {a2:>6}/{b2:<6} == {float( r2 ):13.6f}" )
                updated		= True
    if updated:
        return True
    # OK, got all available a/b --> b/a and a/b * c/b --> a/c.  See if we can find any routes
    # between the desired a/b pairs.
    for (a,b),r in conversions.items():
        if r is not None:
            continue
        for c2,r2 in conversions.items():
            if r2 and a in c2:
                for c3,r3 in conversions.items():
                    if c2 != c3 and r3 and b in c3 and ( x_s := set( c2 ).intersection( set( c3 ))):
                        # We want a/b and we have found a/x or x/a, and b/x or x/b.  Assume their
                        # inverse is in conversions, and is (also) non-zero.
                        log.warning( f"Found intersection between {c2!r} and {c3!r}: {x_s!r}" )
                        x,	= x_s
                        conversions[a,b] = conversions[a,x] * conversions[b,x]
                        log.info( f"Compute {a:>6}/{b2:<6} = {float( conversions[a,b] )} from {a:>6}/{x:<6} == {float( conversions[a,x] ):13.6f} and {b:>6}/{x:<6} == {float( conversions[b,x] ):13.6f}" )
                        conversions[b,a] = 1 / conversions[a,b]
                        return True

    # No more currency pairs are deducible from our present data; If no more are desired (contain
    # None), then we can return falsey (we're done), otherwise, raise an Exception or return truthy:
    # a description of what pairs remain undefined.
    remains			= commas( sorted( f'{a}/{b}' for (a,b),r in conversions.items() if r is None ), final='and' )
    if not remains:
        return False
    resolved			= commas( sorted( f'{a}/{b}' for (a,b),r in conversions.items() if r and r > 1 ), final='and' )
    msg				= f"Failed to find ratio(s) for {remains} via {resolved}"
    if verify:
        raise RuntimeError( msg )
    log.warning( msg )
    return msg


def cryptocurrency_symbol( name, chain=None, w3_url=None, use_provider=None ):
    try:
        return Account.supported( name )
    except ValueError as exc:
        log.info( f"Could not identify currency {name!r} as a supported Cryptocurrency: {exc}" )
    # Not a known core Cryptocurrency; a Token?
    try:
        return tokeninfo( name, w3_url=w3_url, use_provider=use_provider ).symbol
    except Exception as exc:
        log.warning( f"Failed to identify currency {name!r} as an ERC-20 Token: {exc}" )
        raise


def cryptocurrency_proxy( name, decimals=None, chain=None, w3_url=None, use_provider=None ):
    """Return the named ERC-20 Token (or a known "Proxy" token, eg. BTC -> WBTC).

    """
    try:
        return tokeninfo( name, w3_url=w3_url, use_provider=use_provider )
    except Exception as exc:
        log.info( f"Could not identify currency {name!r} as an ERC-20 Token: {exc}" )
    # Not a known Token; a core known Cryptocurrency?
    return cryptocurrency_known( name, decimals=decimals )


def cryptocurrency_known( name, decimals=None ):
    """If it is a recognized core supported Cryptocurrency, return a TokenInfo useful for formatting.
    Since Bitcoin (and other similar cryptocurrencies) are typically assumed to have 8 decimal
    places (the Sat(oshi) is 1/10^8 of a Bitcoin), we'll make the default decimals//3 precision work
    out to 8).

    """
    try:
        symbol			= Account.supported( name )
    except ValueError as exc:
        log.info( f"Failed to identify currency {name!r} as a supported Cryptocurrency: {exc}" )
        raise
    return TokenInfo(
        name		= Account.CRYPTO_SYMBOLS[symbol],
        symbol		= symbol,
        decimals	= 24 if decimals is None else decimals,
        icon		= next( ( Path( __file__ ).resolve().parent / "Cryptos" ).glob( symbol + '*.*' ), None ),
    )


class Invoice:
    """The totals for some invoice line items, in terms of some currencies, payable into some
    Cryptocurrency accounts.

    - Each account's native cryptocurrency symbol (at least) is reflected in computed invoice totals.
      - Eg. if ETH, BTC, XRP and DOGE Accounts are provided, we'll totalize into all 4.
    - Each currency must correspond to one cryptocurrency account (eg. Ethereum ERC-20s --> ETH account)
      - Eg. "US Dollar" (USDC) or "Wrapper Bitcoin" (WBTC) --> ETH, "Bitcoin" or BTC --> BTC
    - Each currency can either be supplied a ratio in conversions, or have a "Proxy" Token for an Oracle
      - Eg. "BTC" --> WBTC Token, "XRP" --> conversions[('XRP','BTC'): 0.00001797

    Currencies may be supplied as a recognized slip39.Account.supported( <name> ); full lower-case
    names in Account.CRYPTO_NAMES.keys(), upper-case symbols in Account.CRYPTO_NAMES.values().  For
    all other than BTC and ETH, a conversion ratio to some common currency (eg. USD) must be
    supplied in conversions.

    Otherwise, a ERC-20 token contract address or a token's symbol or full name (for known
    cryptocurrencies eg. "BTC", "ETH", or some known ERC-20 tokens (~top 100).  Presently, we only
    support obtaining price ratios for invoice cryptocurrencies that have a highly-liquid Ethereum
    ERC-20 "proxy", eg. ETH(WETH), BTC(WBTC).

    Can emit the line items in groups with summary sub-totals and a final total.

    Reframes the price of each line in terms of the Invoice's currencies (default: USD), providing
    "Total <SYMBOL>" and "Taxes <SYMBOL>" for each Cryptocurrency symbols.  NOTE: These are a
    *running* Total; the LineItem Amount is each line's total, in terms of that line's currency.

    Now that we have Web3 details, we can query tokeninfos and hence format currency decimals
    correctly.

    """
    def __init__(
        self, lines,
        accounts: Sequence[Account],		 # [ <Account>, ... ]   .crypto is symbol, eg. BTC, ETH, XRP
        currencies: Optional[List]	= None,	 # "USD" | [ "USD", "BTC" ] (first-most currencies/accounts is conversion "reference" currency)
        conversions: Optional[Dict]	= None,  # { ("USD","ETH"): 1234.56, ("USD","BTC"): 23456.78, ...}
        w3_url			= None,
        use_provider		= None,
    ):
        self.lines		= list( lines )
        self.w3_url		= w3_url
        self.use_provider	= use_provider

        # Collect all desired Invoice currencies; named, and those associated with supplied
        # accounts.  These are symbols, names, or ERC-20 token addresses.  Some may translate into
        # things we can get prices for via an off-chain Oracle via the Ethereum blockchain, but some
        # may not -- these must be supplied w/ a ratio in conversions, to at least one token we *do*
        # have the ability to get the value of.  This requires the caller to have some kind of price
        # feed or oracle of their own; it is recommended to use the 1inch OffchainOracle instead, by
        # sticking to the main Cryptocurrencies for which we have real-time price proxies,
        # eg. USD(USDC), BTC(WBTC), ETH(WETH).
        if isinstance( currencies, str ):
            currencies		= [ currencies ]
        if not currencies:
            currencies		= [ INVOICE_CURRENCY ]
        currencies		= set( currencies )
        log.info( f"Given {len( currencies )} Invoice currencies: {commas( currencies, final='and')}" )

        # Convert all known Crypto-currencies or Tokens to symbols (all upper-case).  Any
        # unrecognized as known Cryptos or Tokens will raise an Exception.  This effectively de-dups
        # all accounts/currencies, but doesn't substitute know "proxy" tokens (eg. BTC <-> WBTC)
        currencies		= set(
            cryptocurrency_symbol( c, w3_url=w3_url, use_provider=use_provider )
            for c in currencies
        )
        log.info( f"Found {len( currencies )} Invoice currency symbols: {commas( currencies, final='and')}" )

        # Associate any Crypto accounts provided w/ their core cryptos (adding any new ones from
        # accounts, to self.currencies).  After this every Invoice currency symbol is in
        # currencies_account.keys(), and every one with a provided account address is in
        # currencies_account[symbol]
        currencies_account	= { c: None for c in currencies }
        if accounts:
            for a in accounts:
                assert currencies_account.get( a.symbol ) is None, \
                    f"Duplicate accounts given for {a.symbol}: {a.address} vs. {currencies_account[a.symbol]}"
                currencies_account[a.symbol] = a
        currencies		= set( currencies_account )
        log.info( f"Found {len( currencies )} Invoice currency symbols + accounts: {commas( currencies, final='and')}" )

        # Associate any Crypto/Tokens w/ available ERC-20 proxies (eg. BTC -> WBTC), and any ERC-20s
        # w/ any supplied ETH account (eg.USDC, WBTC --> <ETH account>) Thus, if BTC was selected
        # and an Ethereum account provided, the buyer can pay in BTC to the Bitcoin account, or in
        # ETH or WBTC to the Ethereum account.  This will add the symbols for all Crypto proxies to
        # currencies_account.
        currencies_proxy	= {}
        for c in currencies:
            try:
                currencies_proxy[c] = tokeninfo( c, w3_url=w3_url, use_provider=use_provider )
            except Exception as exc:
                log.info( f"Failed to find proxy for Invoice currency {c}: {exc}" )
            else:
                # Yup; a proxy for a Crypto Eg. BTC -> WBTC was found, or a native ERC-20 eg. USDC
                # was found; associate it with any ETH account provided.
                if eth := currencies_account.get( 'ETH' ):
                    currencies_account[currencies_proxy[c].symbol] = eth
        log.info( f"Found {len( currencies_proxy )} Invoice currency proxies: {commas( ( f'{c}: {p.symbol}' for c,p in currencies_proxy.items() ), final='and')}" )
        log.info( f"Added {len( set( currencies_account ) - currencies )} proxies: {commas( set( currencies_account ) - currencies, final='and' )}" )
        currencies		= set( currencies_account )

        # Find all LineItem.currency -> Invoice.currencies conversions required.  This establishes
        # the baseline conversions ratio requirements to convert LineItems to each Invoice currency.
        # No prices are yet found.  After this, currencies_proxy will contain all Invoice and LineItem
        # Crypto proxies
        if conversions is None:
            conversions		= {}
        line_currencies		= set(
            line.currency or INVOICE_CURRENCY
            for line in self.lines
        )
        line_symbols		= set(
            cryptocurrency_symbol( lc )
            for lc in line_currencies
        )
        log.info( f"Found {len( line_symbols )} LineItem currencies: {commas( line_symbols, final='and')}" )
        for ls in line_symbols:
            for c in currencies:
                if ls != c:
                    conversions.setdefault( (ls,c), None )  # eg. ('USDC','BTC'): None

        # Finally, add all remaining Invoice and LineItem cryptocurrencies to currencies_proxy, by
        # their original names, symbols and names.  Now, every Invoice and LineItem currency (by
        # name and alias) is represented in currencies_proxy.
        for lc in line_currencies | currencies:
            proxy		= cryptocurrency_proxy( lc, w3_url=w3_url, use_provider=use_provider )
            for alias in set( (lc, proxy.name, proxy.symbol) ):
                if alias in currencies_proxy:
                    assert currencies_proxy[alias] == proxy, \
                        f"Incompatible LineItem.currency {lc!r} w/ currency {alias!r}: \n{proxy} != {currencies_proxy[alias]}"
                currencies_proxy[alias] = proxy
        log.info( f"Found {len( currencies_proxy )} Invoice and LineItem currencies: {commas( ( f'{n}: {p.symbol}' for n,p in currencies_proxy.items() ), final='and')}" )

        # Resolve all resolvable conversions (ie. from any supplied), see what's left
        while ( remaining := conversions_remaining( conversions ) ) and not isinstance( remaining, str ):
            print( f"Working: \n{conversions_table( conversions )}" )
        log.warning( f"{'Remaining' if remaining else 'Resolved'}:\n{conversions_table( conversions )}\n{f'==> {remaining}' if remaining else ''}" )

        while remaining:
            # There are unresolved LineItem -> Invoice currencies.  We need to get a price ratio between
            # the LineItem currency, and at least one of the main Invoice currencies.  Since we know we're dealing
            # in Ethereum ERC-20 proxies, we'll keep getting ratios between currencies and ETH (the
            # default from tokenprices).
            candidates		= filter(
                lambda c: c != 'ETH',
                sum( ( pair for pair,ratio in conversions.items() if ratio is None ), () )
            )
            for c in candidates:
                try:
                    (one,two,ratio),	= tokenprices( c, w3_url=w3_url, use_provider=use_provider )
                except Exception as exc:
                    log.warning( f"Ignoring {c}: {exc}" )
                    continue
                if conversions.get( (c,two.symbol) ) is None or conversions.get( (one.symbol,two.symbol) ) is None:
                    log.info( f"Updated {c:>6}/{two.symbol:<6} = {conversions.get( (c,two.symbol) )}"
                              f" and {one.symbol:>6}/{two.symbol:<6} = {conversions.get( (one.symbol,two.symbol) )},"
                              f" to: {ratio}" )
                    conversions[c,two.symbol] = ratio
                    if c != one.symbol:
                        conversions[one.symbol,two.symbol] = ratio
                    break
            else:
                raise RuntimeError( f"Failed to resolve {remaining}, using candidates {commas( candidates, final='and' )}" )
            while ( remaining := conversions_remaining( conversions ) ) and not isinstance( remaining, str ):
                print( f"Working: \n{conversions_table( conversions )}" )
            log.warning( f"{'Remaining' if remaining else 'Resolved'}:\n{conversions_table( conversions )}\n{f'==> {remaining}' if remaining else ''}" )

        self.currencies		= currencies		# { "USDC", "BTC", ... }
        self.currencies_account	= currencies_account    # { "USDC": "0xaBc...12D", "BTC": "bc1...", ... }
        self.currencies_proxy	= currencies_proxy      # { "BTC": TokenInfo( ... ), ... }
        self.conversions	= conversions		# { ("BTC","ETH"): 14.3914, ... }

    def headers( self ):
        """Output the headers to use in tabular formatting of iterator.  By default, we'd recommend hiding any starting
        with an _ prefix."""
        return (
            '_#',
            'Description',
            'Units',
            'Price',
            '_Tax',
            'Tax %',
            'Taxes',
            'Net',
            'Amount',
            'Currency',
            '_Symbol',
            '_Decimals',
            '_Token',
        ) + tuple(
            f"_Total {currency}"
            for currency in sorted( self.currencies )
        ) + tuple(
            f"_Taxes {currency}"
            for currency in sorted( self.currencies )
        )

    def __iter__( self ):
        """Iterate of lines, computing totals in each Invoice.currencies

        Note that numeric values may be int, float or Fraction, and these are retained through
        normal mathematical operations.

        The number of decimals desired for each line is provided in "_Decimals".  The native number
        of decimals must be respected in this line's calculations.  For example, if eg.  a
        0-decimals Token is used, the Net, Tax and Amount are rounded to 0 decimals.  The sums in
        various currencies converted from each line are not rounded; the currency ratio and hence
        sum is full precision, and is only rounded at the final use.

        """

        # Get all the eg. wBTC / USDC value ratios for the Line-item currency, vs. each Invoice
        # currency at once, in case the iterator takes considerable time; we don't want to risk that
        # memoization "refresh" the token values while generating the invoice!
        tot			= {
            c: 0. for c in self.currencies
        }
        tax			= {
            c: 0. for c in self.currencies
        }

        for i,line in enumerate( self.lines ):
            line_currency	= line.currency or INVOICE_CURRENCY
            line_amount,line_taxes,line_taxinf = line.net()

            line_curr		= tokeninfo( line_currency, w3_url=self.w3_url, use_provider=self.use_provider )
            line_symbol		= line_curr.symbol
            line_decimals	= line_curr.decimals // 3 if line.decimals is None else line.decimals

            line_amount		= round( line_amount, line_decimals )
            line_taxes		= round( line_taxes, line_decimals )
            line_net		= line_amount - line_taxes

            for c in self.currencies:
                if line_curr.symbol == c:
                    tot[c]     += line_amount
                    tax[c]     += line_taxes
                else:
                    tot[c]     += line_amount * self.conversions[line_curr.symbol,c]
                    tax[c]     += line_taxes  * self.conversions[line_curr.symbol,c]
            yield (
                i,			# The LineItem #, and...
                line.description,
                line.units,
                line.price,
                line.tax,
                line_taxinf,
                line_taxes,
                line_net,
                line_amount,
                line_currency,		# the line's currency
                line_symbol,		# and Token symbol
                line_decimals,		# the desired number of decimals
                line_curr,		# and the associated tokeninfo
            ) + tuple(
                tot[c] for c in sorted( self.currencies )
            ) + tuple(
                tax[c] for c in sorted( self.currencies )
            )

    def pages(
        self,
        page		= None,
        rows		= None,
    ):
        """Yields a sequence of lists containing rows, paginated into 'rows' chunks.

        if page (zero-basis) specified, only yields matching pages.
        """
        if rows is None:
            rows		= INVOICE_ROWS

        def page_match( i ):
            if page is None:
                return True
            if hasattr( page, '__contains__' ):
                return i in page
            return i == page

        page_i,page_l		= 0,[]
        for row in iter( self ):
            page_l.append( row )
            if len( page_l ) >= rows:
                if page_match( page_i ):
                    yield page_l
                page_i,page_l	= page_i+1,[]
        if page_l and page_match( page_i ):
            yield page_l

    def tables(
        self, *args,
        tablefmt	= None,
        columns		= None,		# list (ordered) set/predicate (unordered)
        totalfmt	= None,
        **kwds				# page, rows, ...
    ):
        """Tabulate columns into textual tables.  Each page yields 3 items:

            <page>,<line-items>,<sub-totals>,''|<total>

        Each interior page includes a subtotals table; the final page also includes the full totals.

        The 'columns' is a filter (a set/list/tuple or a predicate) that selects the columns
        desired; by default, elides any columns having names starting with '_'.  We will accept
        matches case-insensively, and ignoring any leading/trailing '_'.

        If any columns w/ leading '_' *are* selection, we trim the '_' for display.

        """
        headers			= self.headers()

        def can( c ):
            """Canonicalize a header/column name for comparison"""
            return c.strip( '_' ).lower()

        headers_can		= [ can( h ) for h in headers ]
        if columns:
            if is_listlike( columns ):
                try:
                    selected	= tuple( headers_can.index( can( c )) for c in columns )
                except ValueError as exc:
                    raise ValueError( f"Columns not found: {commas( c for c in columns if can( c ) not in headers_can )}" ) from exc
            elif hasattr( columns, '__contains__' ):
                selected	= tuple( i for i,h in enumerate( headers ) if can( h ) in [ can( c ) for c in columns ] )
                assert selected, \
                    "No columns matched"
            else:
                # User-provided column predicate; do not canonicalize
                selected	= tuple( i for i,h in enumerate( headers ) if columns( h ) )
        else:
            # Default; just ignore _... columns
            selected		= tuple( i for i,h in enumerate( headers ) if not h.startswith( '_' ) )
        headers_selected	= tuple( headers[i] for i in selected )

        log.info( f"Tabulating indices {commas(selected, final='and')}: {commas( headers_selected, final='and' )}" )
        pages			= list( self.pages( *args, **kwds ))

        # Overall formatted decimals for the entire invoice; use the greatest desired decimals of
        # any token/line, based on Cryptocurrency proxies.  Individual line items may have been
        # rounded to lower decimals.
        decimals_i		= headers_can.index( can( '_Decimals' ))
        decimals		= max( line[decimals_i] for page in pages for line in page )
        floatfmt		= f',.{decimals}f'
        intfmt			= ','
        page_prev		= None
        for p,page in enumerate( pages ):
            table		= tabulate(
                # Tabulate the line items
                [[line[i] for i in selected] for line in page],
                headers		= [ h.strip('_') for h in headers_selected ],
                intfmt		= intfmt,
                floatfmt	= floatfmt,
                tablefmt	= tablefmt or 'orgtbl',
            )
            first		= page_prev is None
            final		= p + 1 == len( pages )

            # {Sub}total for payment cryptocurrrencies are rounded to the individual
            # Cryptocurrency's designated decimals // 3.  For typical ERC-20 tokens, this is
            # eg. USDC: 6 // 3 == 2, WBTC: 18 // 3 == 6.  For known Cryptocurrencies, eg. BTC: 24 //
            # 3 == 8.  TODO: There should be a more sensible / less brittle way to do this.
            def deci( c ):
                try:
                    return cryptocurrency_known( c ).decimals // 3
                except Exception:
                    return self.currencies_proxy[c].decimals // 3

            def toti( c ):
                return headers_can.index( can( f'_Total {c}' ))

            def taxi( c ):
                return headers_can.index( can( f'_Taxes {c}' ))

            subtotal		= tabulate(
                # And the per-currency Sub-totals (for each page)
                [
                    [
                        self.currencies_account[c].address,
                        c,
                        self.currencies_account[c].name if c == self.currencies_account[c].symbol else self.currencies_proxy[c].name,
                    ] + [
                        round( page[-1][taxi( c )], deci( c )),
                        round( page[-1][toti( c )], deci( c )),
                    ] if first else [
                        round( page[-1][taxi( c )] - page_prev[-1][taxi( c )], deci( c )),
                        round( page[-1][toti( c )] - page_prev[-1][toti( c )], deci( c )),
                    ]
                    for c in sorted( self.currencies )
                ],
                headers		= (
                    'Account',
                    'Crypto',
                    'Currency',
                    'Taxes' if final else f'Taxes {p+1}/{len( pages )}',
                    'Subtotal' if final else f'Subtotal {p+1}/{len( pages )}',
                ),
                intfmt		= ',',
                floatfmt	= ',g',
                tablefmt	= tablefmt or 'orgtbl',
            )
            total		= tabulate(
                # And the per-currency Totals (up to current page)
                [
                    [
                        self.currencies_account[c].address,
                        c,
                        self.currencies_account[c].name if c == self.currencies_account[c].symbol else self.currencies_proxy[c].name,
                        round( page[-1][taxi( c )], deci( c )),
                        round( page[-1][toti( c )], deci( c )),
                    ]
                    for c in sorted( self.currencies )
                ],
                headers		= (
                    'Account',
                    'Crypto',
                    'Currency',
                    'Taxes' if final else f'Taxes {p+1}/{len( pages )}',
                    'Total' if final else f'Total {p+1}/{len( pages )}',
                ),
                intfmt		= ',',
                floatfmt	= ',g',
                tablefmt	= tablefmt or 'orgtbl',
            )

            yield page, table, subtotal, total


def layout_invoice(
    inv_dim: Coordinate,			# Printable invoice dimensions, in inches (net page margins).
    inv_margin: int,				# Additional margin around invoice
    rows: int,
):
    """Layout an Invoice, in portrait format.

     Rotate the  watermark, etc. so its angle is from the lower-left to the upper-right.

                 b
          +--------------+        +--------------+
          |             .         |I.. (img)  Na.|
          |           D.          |--------------|
          |          .            |# D.. u.u.    |
          |        I.             |...           |
          |       .               |         ---- |
          |     A. c              |    BTC  #.## |
          |    .                  |    ETH  #.## |
        a |  P.                   | (terms)      |
          |β.                     | (tax #, ..)  |
          + 90-β                  +--------------+

       tan(β) = b / a, so
       β = arctan(b / a)

    Sets priority:
      -3     : Hindmost backgrounds
      -2     : Things atop background, but beneath contrast-enhancement
      -1     : Contrast-enhancing partially transparent images
       0     : Text, etc. (the default)

    All sizes in mm.

    """
    prio_backing		= -3
    prio_normal			= -2
    prio_contrast		= -1

    if inv_margin is None:
        inv_margin		= 0		# Default; no additional margin (besides page margins)

    inv				= Box( 'invoice', 0, 0, inv_dim.x, inv_dim.y )
    inv_interior		= inv.add_region_relative(
        Region( 'inv-interior', x1=+inv_margin, y1=+inv_margin, x2=-inv_margin, y2=-inv_margin )
    ).add_region_proportional(
        # inv-image	-- A full background image, out to the margins; bottom-most in stack
        Image(
            'inv-image',
            priority	= prio_backing,
        )
    )

    a				= inv_interior.h
    b				= inv_interior.w
    c				= math.sqrt( a * a + b * b )    # noqa: F841
    β				= math.atan( b / a )		# noqa: F841
    rotate			= 90 - math.degrees( β )        # noqa: F841

    head			= 25/100		# 25% header, 70% body
    foot			= 95/100		# 5% footer

    # inv-head: Image for header of Invoice (if no inv-image)
    inv_head			= inv_interior.add_region_proportional(
        Image(
            'inv-head',
            y2		= head,
            priority	= prio_normal,
        ),
    )

    # inv-label: Label "Invoice"
    inv_head.add_region_proportional(
        Image(
            'inv-label-bg',
            x1		= 0,
            y1		= 5/8,
            x2		= 1/4,
            y2		= 7/8,
            priority	= prio_contrast,
        )
    ).add_region(
        Text(
            'inv-label',
            font	= 'mono',
            text	= "Invoice",
        )
    )

    # inv-body, ...: Image for Body of Invoice;
    # inv-table: Main Invoice text area
    inv_interior.add_region_proportional(
        Image(
            'inv-body',
            y1		= head,
            y2		= foot,
            priority	= prio_normal,
        )
    ).add_region_proportional(
        Image(
            'inv-table-bg',
            priority	= prio_contrast,
        ),
    ).add_region_proportional(
        Text(
            'inv-table',
            y2		= 1/rows,
            font	= 'mono',
            size_ratio	= 9/16,
            multiline	= True,
        )
    )

    # inv-foot: Image for bottom of Invoice (if no inv-image)
    inv_interior.add_region_proportional(
        Image(
            'inv-foot',
            y1		= foot,
            priority	= prio_normal,
        ),
    )

    return inv


def datetime_advance( dt, years=None, months=None, days=None, hours=None, minutes=None, seconds=None ):
    """Advance a datetime the specified amount.  Differs from timedelta, in that A) months are supported
    (so we must compute the target month, and clamp the day number appropriately).  Otherwise, uses
    timedelta.

    """
    if years or months:
        yr,mo,dy		= dt.year,dt.month,dt.day
        yr		       += years or 0
        mo		       += months or 0
        if mo > 12:
            yr		       += ( mo - 1 ) // 12
            mo			= ( mo - 1 ) % 12 + 1
            assert 1 <= mo <= 12
        _,dy_max		= monthrange( yr, mo )
        if dy > dy_max:
            dy			= dy_max
        dt			= dt.replace( day=1 ).replace( year=yr ).replace( month=mo ).replace( day=dy )
    if days or hours or minutes or seconds:
        dt		       += timedelta( days=days or 0, hours=hours or 0, minutes=minutes or 0, seconds=seconds or 0 )
    return dt


@dataclass
class Contact:
    name: str					# Company or Individual eg. "Dominion Research and Development Corp."
    contact: str				# client/vendor authority eg. "Perry Kundert <perry@dominionrnd.com>"
    address: Optional[str]	= None		# multi-line mailing/delivery address


@dataclass
class InvoiceMetadata:
    """Collected Invoice metadata, required to generate an Invoice"""
    vendor: Contact
    client: Contact
    date: datetime
    due: datetime
    number: str					# eg. INV-20230131-0001
    directory: Path				# Location of assets (and invoices)


@dataclass
class InvoiceOutput:
    invoice: Invoice
    metadata: InvoiceMetadata
    pdf: fpdf.FPDF
    path: Optional[Path]


def produce_invoice(
    invoice: Invoice,				# Invoice LineItems, Cryptocurrency Account data
    client: Contact,    	  		# Client's identifying info (eg. Name, Attn, Address)
    vendor: Contact,				# Vendor's identifying info
    directory: Optional[Union[Path,str]] = None,  # Look here for files (eg. image assets), invoices
    inv_number: Optional[Union[str,int]] = None,  # eg. "CLIENT-20230930-0001" (default: <client>-<date>-<num>)
    inv_date: Optional[datetime] = None,
    inv_due: Optional[Any]	= None, 	# another datetime, or args/kwds for datetime_advance
    terms: Optional[str]	= None, 	# eg. "Payable on receipt in $USDC, $ETH, $BTC"
    conversions: Optional[Dict]	= None,
    rows: Optional[int]		= None,
    paper_format: Any		= None, 	# 'Letter', 'Legal', 'A4', (x,y) dimensions in mm.
    orientation: Optional[str]	= None,		# available orientations; default portrait, landscape
    inv_image: Optional[Union[Path,str]] = None,  # A custom background image (Path or name relative to directory/'.'
):
    """Produces a PDF containing the supplied Invoice details, optionally with a PAID watermark.



    """
    if isinstance( directory, (str,type(None))):
        directory			= Path( directory or '.' )
    assert isinstance( directory, (Path,type(None)))
    log.info( f"Dir.:  {directory}" )

    if isinstance( inv_image, (str,type(None))):
        inv_image		= directory / ( inv_image or 'inv-image.*' )
        if not inv_image.exists():
            inv_image		= None
    assert isinstance( inv_image, (Path,type(None)))
    log.info( f"Image: {inv_image}" )

    # Any datetime WITHOUT a timezone designation is re-interpreted as the local timezone of the
    # invoice issuer, or UTC.
    if inv_date is None:
        inv_date		= datetime.utcnow().astimezone( timezone.utc )
    if inv_date.tzname() is None:
        try:
            inv_zone		= get_localzone()
        except Exception:
            inv_zone		= timezone.utc
        inv_date		= inv_date.astimezone( inv_zone )

    log.info( f"Date:  {inv_date.strftime( INVOICE_STRFTIME )}" )
    if not isinstance( inv_due, datetime ):
        if not inv_due:
            inv_due		= INVOICE_DUE
        if is_mapping( inv_due ):
            inv_due		= datetime_advance( inv_date, **dict( inv_due ))
        elif is_listlike( inv_due ):
            inv_due		= datetime_advance( inv_date, *tuple( inv_due ))
        elif isinstance( inv_due, timedelta ):
            inv_due		= inv_date + inv_due
        else:
            raise ValueError( f"Unsupported Invoice due date: {inv_due!r}" )
    log.info( f"Due:   {inv_due.strftime( INVOICE_STRFTIME )}" )
    if inv_number is None:
        cli			= client.name.split()[0].upper()[:3] if client else 'INV'
        ymd			= inv_date.strftime( '%Y%m%d' )
        key			= f"{cli}-{ymd}"
        produce_invoice.inv_count[key] += 1
        num			= produce_invoice.inv_count[key]
        inv_number		= f"{cli}-{ymd}-{num:04d}"
    log.info( f"Num.:  {inv_number}" )

    metadata			= InvoiceMetadata(
        vendor		= vendor,
        client		= client,
        date		= inv_date,
        due		= inv_due,
        number		= inv_number,
        directory	= directory,
    )

    if conversions is None:
        conversions		= {}

    # Default to full page, given the desired paper and orientation.  All PDF dimensions are mm.
    invs_pp,orientation,page_xy,pdf,comp_dim = layout_pdf(
        paper_format	= paper_format,
        orientation	= orientation,
    )
    log.info( f'Dim.: {comp_dim.x / MM_IN:6.3f}" x {comp_dim.y / MM_IN:6.3f}"' )

    # TODO: compute rows based on line lengths; the longer the line, the smaller the lines required
    if rows is None:
        rows			= INVOICE_ROWS

    # Compute the Invoice layout on the page.  All page layouts are specified in inches.
    inv_dim			= Coordinate( comp_dim.x / MM_IN, comp_dim.y / MM_IN )
    inv				= layout_invoice( inv_dim=inv_dim, inv_margin=0, rows=rows )

    inv_elements		= list( inv.elements() )
    if log.isEnabledFor( logging.DEBUG ):
        log.debug( f"Invoice elements: {json.dumps( inv_elements, indent=4)}" )
    inv_tpl			= fpdf.FlexTemplate( pdf, inv_elements )

    p_cur			= None
    details			= list( invoice.tables() )
    for i,(page,tbl,sub,tot) in enumerate( details ):
        p,(offsetx,offsety)		= page_xy( i )
        if p != p_cur:
            pdf.add_page()

        here			= Path( __file__ ).resolve().parent
        layout			= here.parent / 'layout'
        #crypto			= here / 'Crypto'

        last			= i + 1 == len( details )
        inv_tpl['inv-image']	= inv_image
        inv_tpl['inv-table']	= f"{tbl}\n\n{80 * ( '=' if last else '-' )}\n{tot if last else sub}"
        inv_tpl['inv-label-bg']	= layout / '1x1-ffffffbf.png'
        inv_tpl['inv-table-bg']	= layout / '1x1-ffffffbf.png'

        inv_tpl.render( offsetx=offsetx, offsety=offsety )
    # Caller already has the Invoice; return the PDF and computed InvoiceMetadata
    return (paper_format,orientation),pdf,metadata
produce_invoice.inv_count	= defaultdict( int )  # noqa: E305


def write_invoices(
    invoices,				# sequence of [ Invoice, ... ] or { "<name>": Invoice, ... }
    filename		= True,		# A file name/Path, if PDF output to file is desired; ''/True implies default., False no file
    **kwds
):
    """Create unique cryptocurrency account(s) for each client invoice, generate the invoice, and
    (optionally) write them to files.  Yields a sequence of the generate invoice PDF names and
    details.

    """
    if filename is None:
        filename		= True
    for invoice in invoices:
        _,pdf,metadata		= produce_invoice(
            invoice,
            **kwds
        )

        accounts		= invoice.accounts
        assert accounts, \
            "At least one Cryptocurrency account must be specified"
        for account in accounts:
            log.warning( f"{account.crypto:6} {account.path:20}: {account.address}" )

        pdf_name		= (( '' if filename is True else filename ) or FILENAME_FORMAT ).format(
            name	= metadata.number,
            date	= datetime.strftime( metadata.date, '%Y-%m-%d' ),
            time	= datetime.strftime( metadata.date, '%H.%M.%S'),
            crypto	= accounts[0].crypto,
            address	= accounts[0].address,
        )
        if not pdf_name.lower().endswith( '.pdf' ):
            pdf_name	       += '.pdf'

        path			= None
        if filename is not False:
            path		= invoice.directory.resolve() / pdf_name
            log.warning( f"Writing Invoice {metadata.number!r} to: {path}" )
            pdf.output( path )

        yield pdf_name, InvoiceOutput( invoice=invoice, metadata=metadata, pdf=pdf, path=path )
