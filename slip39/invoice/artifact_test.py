import json
import random
import math
import logging

from fractions		import Fraction
from pathlib		import Path

import pytest

import tabulate

from crypto_licensing.misc import parse_datetime

from ..util		import ordinal, commas
from ..api		import account, accounts
from .artifact		import (
    LineItem, Invoice, InvoiceMetadata, conversions_remaining, conversions_table, Contact,
    produce_invoice, write_invoices,
)

log				= logging.getLogger( "artifact_test" )

SEED_ZOOS			= 'zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo wrong'


def test_conversions():
    print( f"tabulate version: {tabulate.__version__}" )
    c0_tbl = tabulate.tabulate( [[ 1.23],[12345.6789],[.0001234]], floatfmt=",.6g", tablefmt="orgtbl" )
    print( f"\n{c0_tbl}" )
    assert c0_tbl == """\
|      1.23      |
| 12,345.7       |
|      0.0001234 |"""

    c1				= {
        ('ETH','USD'):	1234.56,
        ('BTC','USD'):	23456.78,
        ('BTC','ETH'): None,
    }
    c1_tbl			= conversions_table( c1, tablefmt='orgtbl' )
    print( '\n' + c1_tbl )
    assert c1_tbl == """\
| Coin   | in ETH   |    in USD |
|--------+----------+-----------|
| BTC    | ?        | 23,456.78 |
| ETH    |          |  1,234.56 |
| USD    |          |           |"""

    c_simple			= dict( c1 )
    c_simple_i			= 0
    while ( conversions_remaining( c_simple )):
        c_simple_i	       += 1
    assert c_simple_i == 1
    c_simple_tbl		= conversions_table( c_simple, tablefmt='orgtbl' )
    print( c_simple_tbl )
    assert c_simple_tbl == """\
| Coin   |     in BTC |    in ETH |    in USD |
|--------+------------+-----------+-----------|
| BTC    |            | 19.000113 | 23,456.78 |
| ETH    | 0.05263126 |           |  1,234.56 |
| USD    |            |           |           |"""

    c_w_doge			= dict( c1, ) | { ('DOGE','BTC'): .00000385, ('DOGE','USD'): None }
    c_w_doge_i			= 0
    while ( conversions_remaining( c_w_doge )):
        c_w_doge_i	       += 1
    assert c_w_doge_i == 2
    assert c_w_doge == {
        ('BTC', 'ETH'): pytest.approx( 19.00011, rel=1/1000 ),
        ('BTC', 'USD'): pytest.approx( 23456.78, rel=1/1000 ),
        ('ETH', 'BTC'): pytest.approx( 0.052631, rel=1/1000 ),
        ('ETH', 'USD'): pytest.approx( 1234.56,  rel=1/1000 ),
        ('USD', 'BTC'): pytest.approx( 4.263159e-05, rel=1/1000 ),
        ('USD', 'ETH'): pytest.approx( 8.100051e-04, rel=1/1000 ),
        ('BTC', 'DOGE'): pytest.approx( 259740.2597, rel=1/1000 ),
        ('DOGE', 'BTC'): pytest.approx( 3.85e-06, rel=1/1000 ),
        ('DOGE', 'ETH'): pytest.approx( 7.31504e-05, rel=1/1000 ),
        ('DOGE', 'USD'): pytest.approx( 0.090308, rel=1/1000 ),
        ('ETH', 'DOGE'): pytest.approx( 13670.45839, rel=1/1000 ),
        ('USD', 'DOGE'): pytest.approx( 11.07314216, rel=1/1000 ),
    }
    c_w_doge_tbl		= conversions_table( c_w_doge, tablefmt='orgtbl' )
    print( c_w_doge_tbl )
    assert c_w_doge_tbl == """\
| Coin   |     in BTC |        in DOGE |    in ETH |         in USD |
|--------+------------+----------------+-----------+----------------|
| BTC    |            | 259,740.26     | 19.000113 | 23,456.78      |
| DOGE   |            |                |           |      0.0903086 |
| ETH    | 0.05263126 |  13,670.458    |           |  1,234.56      |
| USD    |            |      11.073142 |           |                |"""

    c_w_doge_all		= conversions_table( c_w_doge, greater=False, tablefmt='orgtbl' )
    print( c_w_doge_all )
    assert c_w_doge_all == """\
| Coin   |     in BTC |        in DOGE |      in ETH |         in USD |
|--------+------------+----------------+-------------+----------------|
| BTC    |            | 259,740.26     | 19.000113   | 23,456.78      |
| DOGE   | 3.85e-06   |                |  7.315e-05  |      0.0903086 |
| ETH    | 0.05263126 |  13,670.458    |             |  1,234.56      |
| USD    | 4.263e-05  |      11.073142 |  0.00081001 |                |"""

    c_bad			= dict( c1, ) | { ('DOGE','USD'): None }
    with pytest.raises( Exception ) as c_bad_exc:
        c_bad_i			= 0
        while ( done := conversions_remaining( c_bad, verify=True )):
            c_bad_i	       += 1
        assert done is None
    assert 'Failed to find ratio(s) for DOGE/USD via BTC/ETH, BTC/USD and ETH/USD' in str( c_bad_exc )
    assert c_bad_i == 1

    assert conversions_remaining( c_bad ) == "Failed to find ratio(s) for DOGE/USD via BTC/ETH, BTC/USD and ETH/USD"

    # Ensure we can handle zero-valued tokens
    c_zero			= dict( c1, ) | {('WEENUS','ETH'): 0, ('ZEENUS','ETH'): 0, ('ZEENUS','WEENUS'): None }
    c_zero_i			= 0
    while ( conversions_remaining( c_zero, verify=True )):
        c_zero_i	       += 1
    assert c_zero_i == 1
    assert c_zero == {
        ('BTC', 'ETH'): pytest.approx( 19.00011, rel=1/1000 ),
        ('BTC', 'USD'): pytest.approx( 23456.78, rel=1/1000 ),
        ('ETH', 'BTC'): pytest.approx( 0.052631, rel=1/1000 ),
        ('ETH', 'USD'): pytest.approx( 1234.56,  rel=1/1000 ),
        ('USD', 'BTC'): pytest.approx( 4.263159e-05, rel=1/1000 ),
        ('USD', 'ETH'): pytest.approx( 8.100051e-04, rel=1/1000 ),
        ('WEENUS', 'BTC'): 0.0,
        ('WEENUS', 'ETH'): 0,
        ('WEENUS', 'USD'): 0.0,
        ('WEENUS', 'ZEENUS'): 1,
        ('ZEENUS', 'BTC'): 0.0,
        ('ZEENUS', 'ETH'): 0,
        ('ZEENUS', 'USD'): 0.0,
        ('ZEENUS', 'WEENUS'): 1,
    }
    c_zero_tbl			= conversions_table( c_zero, tablefmt='orgtbl' )
    print( c_zero_tbl )
    assert c_zero_tbl == """\
| Coin   |     in BTC |    in ETH |    in USD |   in WEENUS |   in ZEENUS |
|--------+------------+-----------+-----------+-------------+-------------|
| BTC    |            | 19.000113 | 23,456.78 |             |             |
| ETH    | 0.05263126 |           |  1,234.56 |             |             |
| USD    |            |           |           |             |             |
| WEENUS | 0          |  0        |      0    |             |           1 |
| ZEENUS | 0          |  0        |      0    |           1 |             |"""


line_amounts			= [
    [
        LineItem(
            description	= "Widgets for the Thing",
            units	= 198,
            price	= 2.01,
            tax		= Fraction( 5, 100 ),  # exclusive
            currency	= 'US Dollar',
        ),
        ( 417.879, 19.899, "5% add" ),
    ], [
        LineItem(
            description	= "More Widgets",
            units	= 2500,
            price	= Fraction( 201, 100000 ),
            tax		= Fraction( 5, 100 ),  # exclusive
            currency	= 'ETH',
        ),
        ( 5.27625, .25125, "5% add" ),
    ], [
        LineItem(
            description	= "Something else, very detailed and elaborate to explain in few words, so more elaboration is required",
            units	= 100,
            price	= Fraction( 201, 100000 ),
            tax		= Fraction( 105, 100 ),  # inclusive
            currency	= 'Bitcoin',
        ),
        ( .201, .009571, "5% inc" ),
    ], [
        LineItem(
            description	= "Buy some Holo hosting",
            units	= 12,
            price	= 10101.04030201,
            tax		= Fraction( 5, 100 ),  # inclusive
            currency	= 'HoloToken',
        ),
        ( 127273.107805, 6060.624181, "5% add" ),
    ], [
        LineItem( "Worthless", 12345.67890123, currency='ZEENUS' ),
        ( 12345.6789, 0, "no tax"),
    ], [
        LineItem( "Simple", 12345.67890123 ),  # currency default None ==> USD
        ( 12345.6789, 0, "no tax" ),
    ],
]


@pytest.mark.parametrize( "line, amounts", line_amounts )
def test_LineItem( line, amounts ):
    amount,taxes,taxinf	= amounts
    assert line.net() == (
        pytest.approx( amount, abs=10 ** -3 ),
        pytest.approx( taxes,  abs=10 ** -3 ),
        taxinf
    )


vendor				= Contact(
    name	= "Dominion Research & Development Corp.",
    contact	= "Perry Kundert <perry@dominionrnd.com>",
    phone	= "+1-780-970-8148",
    address	= """\
275040 HWY 604
Lacombe, AB  T4L 2N3
CANADA
""",
    billing	= """\
RR#3, Site 1, Box 13
Lacombe, AB  T4L 2N3
CANADA
""",
)

client				= Contact(
    name	= "Awesome, Inc.",
    contact	= "Great Guy <perry+awesome@dominionrnd.com>",
    address	= """\
123 Awesome Ave.
Schenectady, NY  12345
USA
""",
)


def test_tabulate( tmp_path ):
    accounts			= [
        account( SEED_ZOOS, crypto='Ripple' ),
        account( SEED_ZOOS, crypto='Ethereum' ),
        account( SEED_ZOOS, crypto='Bitcoin' ),
    ]
    conversions			= {
        ("BTC","XRP"): 60000,
    }

    total			= Invoice(
        [
            line
            for line,_ in line_amounts
        ],
        accounts	= accounts,
        currencies	= [ "USD", "HOT" ],
        conversions	= dict( conversions ),
    )

    print( json.dumps( list( total.pages() ), indent=4, default=str ))

    tables			= list( total.tables() )
    for t in tables:
        print( t )

    # Can't test until we can fake up fixed token values

    tables			= list( total.tables(
        columns=('#', 'Description', 'Qty', 'Currency', 'Coin', 'Price', 'Tax %', 'Taxes', 'Amount', 'Total USDC'),
    ))
    for t in tables:
        print( t )

    # Get the default formatting for line's w/ currencies w/ 0 decimals, 0 value.
    worthless = '\n\n====\n\n'.join(
        f"{table}\n\n{sub}\n\n{tot}"
        for _,table,sub,tot in Invoice(
            [
                line
                for line,_ in line_amounts
                if line.currency in ("ZEENUS", )
            ],
            currencies	= ["HOT", "ETH", "BTC", "USD"],
            accounts	= accounts,
            conversions	= dict( conversions ),
        ).tables(
            tablefmt	= 'presto',
        )
    )
    print( worthless )
    assert worthless == """\
 Description                                     |   Qty |   Price | Tax %   |   Taxes |   Amount | Coin
-------------------------------------------------+-------+---------+---------+---------+----------+--------
 Worthless                                       |     1 |  12,346 | no tax  |       0 |   12,346 | ZEENUS
-------------------------------------------------+-------+---------+---------+---------+----------+--------
 BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |       |         |         |       0 |        0 | BTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       |         |         |       0 |        0 | ETH
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       |         |         |       0 |        0 | HOT
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       |         |         |       0 |        0 | USDC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       |         |         |       0 |        0 | WBTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       |         |         |       0 |        0 | WETH
 XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         |       |         |         |       0 |        0 | XRP

 Account                                         |   Taxes |   Subtotal | Coin   | Currency
-------------------------------------------------+---------+------------+--------+---------------
 BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |       0 |          0 | BTC    | Bitcoin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |          0 | ETH    | Ethereum
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |          0 | HOT    | HoloToken
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |          0 | USDC   | USD Coin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |          0 | WBTC   | Wrapped BTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |          0 | WETH   | Wrapped Ether
 XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         |       0 |          0 | XRP    | Ripple

 Account                                         |   Taxes |   Total | Coin   | Currency
-------------------------------------------------+---------+---------+--------+---------------
 BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |       0 |       0 | BTC    | Bitcoin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |       0 | ETH    | Ethereum
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |       0 | HOT    | HoloToken
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |       0 | USDC   | USD Coin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |       0 | WBTC   | Wrapped BTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       0 |       0 | WETH   | Wrapped Ether
 XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         |       0 |       0 | XRP    | Ripple"""  # noqa: E501

    # No conversions of non-0 values; default Invoice currency is USD.  Longest digits should be 2
    # Instead of querying BTC, ETH prices, provide a conversion (so our invoice pricing is static)
    shorter_invoice		= Invoice(
        [
            line
            for line,_ in line_amounts
            if line.currency in ("ZEENUS", None) or line.currency.upper().startswith( 'US' )
        ],
        accounts	= accounts,
        conversions	= dict( conversions ) | {
            (eth,usd): 1500 for eth in ("ETH","WETH") for usd in ("USDC",)
        } | {
            (btc,eth): 15 for eth in ("ETH","WETH") for btc in ("BTC","WBTC")
        },
    )
    # Include some selected columns
    shorter = '\n\n====\n\n'.join(
        f"{table}\n\n{sub}\n\n{tot}"
        for _,table,sub,tot in shorter_invoice.tables(
            columns	= ('#', 'Description', 'Qty', 'Currency', 'Coin', 'Price', 'Tax %', 'Taxes', 'Amount', 'Total USDC'),
            tablefmt	= 'presto',
        )
    )
    print( shorter )
    assert shorter == """\
   # | Description                                     |   Qty | Currency      | Coin   |     Price | Tax %   |       Taxes |          Amount |   Total USDC
-----+-------------------------------------------------+-------+---------------+--------+-----------+---------+-------------+-----------------+--------------
   0 | Widgets for the Thing                           |   198 | US Dollar     | USDC   |      2.01 | 5% add  | 19.9        |    417.88       |       417.88
   1 | Worthless                                       |     1 | ZEENUS        | ZEENUS | 12,346    | no tax  |  0          | 12,346          |       417.88
   2 | Simple                                          |     1 | USD           | USDC   | 12,345.68 | no tax  |  0          | 12,345.68       |    12,763.56
-----+-------------------------------------------------+-------+---------------+--------+-----------+---------+-------------+-----------------+--------------
     | BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |       | Bitcoin       | BTC    |           |         |  0.00088444 |      0.56726933 |
     | ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       | Ethereum      | ETH    |           |         |  0.013267   |      8.50904    |
     | ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       | USD Coin      | USDC   |           |         | 19.9        | 12,763.56       |
     | ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       | Wrapped BTC   | WBTC   |           |         |  0.00088444 |      0.56726933 |
     | ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |       | Wrapped Ether | WETH   |           |         |  0.013267   |      8.50904    |
     | XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         |       | Ripple        | XRP    |           |         | 53.07       | 34,036.16       |

 Account                                         |       Taxes |        Subtotal | Coin   | Currency
-------------------------------------------------+-------------+-----------------+--------+---------------
 BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |  0.00088444 |      0.56726933 | BTC    | Bitcoin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.013267   |      8.50904    | ETH    | Ethereum
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E | 19.9        | 12,763.56       | USDC   | USD Coin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.00088444 |      0.56726933 | WBTC   | Wrapped BTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.013267   |      8.50904    | WETH   | Wrapped Ether
 XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         | 53.07       | 34,036.16       | XRP    | Ripple

 Account                                         |       Taxes |           Total | Coin   | Currency
-------------------------------------------------+-------------+-----------------+--------+---------------
 BTC: bc1qk0a9hr7wjfxeenz9nwenw9flhq0tmsf6vsgnn2 |  0.00088444 |      0.56726933 | BTC    | Bitcoin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.013267   |      8.50904    | ETH    | Ethereum
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E | 19.9        | 12,763.56       | USDC   | USD Coin
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.00088444 |      0.56726933 | WBTC   | Wrapped BTC
 ETH: 0xfc2077CA7F403cBECA41B1B0F62D91B5EA631B5E |  0.013267   |      8.50904    | WETH   | Wrapped Ether
 XRP: rUPzi4ZwoYxi7peKCqUkzqEuSrzSRyLguV         | 53.07       | 34,036.16       | XRP    | Ripple"""  # noqa: E501

    this			= Path( __file__ ).resolve()
    test			= this.with_suffix( '' )

    date			= parse_datetime( "2021-01-01 00:00:00.1 Canada/Pacific" )

    (paper_format,orientation),pdf,metadata = produce_invoice(
        invoice		= shorter_invoice,
        metadata	= InvoiceMetadata(
            vendor	= vendor,
            client	= client,
            directory	= test,
            date	= date,
            label	= 'Quote',
        ),
        #inv_image	= 'dominionrnd-invoice.png',    # Full page background image
        logo		= 'dominionrnd-logo.png',       # Logo 16/9 in bottom right of header
    )

    print( f"Invoice metadata: {metadata}" )
    temp		= Path( tmp_path )
    path		= temp / 'invoice-shorter.pdf'
    pdf.output( path )
    print( f"Invoice saved: {path}" )

    # Finally, generate invoice with all rows, and all conversions from blockchain Oracle (except
    # XRP, for which we do not have an oracle, so must provide an estimate from another source...)
    invoice			= Invoice(
        [
            line
            for line,_ in line_amounts
        ],
        currencies	= ["HOT", "ETH", "BTC", "USD"],
        accounts	= accounts,
        conversions	= {
            ("BTC","XRP"): 60000,
        }
    )
    metadata			= InvoiceMetadata(
        vendor		= vendor,
        client		= client,
        directory	= test,
    )
    (paper_format,orientation),pdf,metadata = produce_invoice(
        invoice		= invoice,
        metadata	= metadata,
        logo		= 'dominionrnd-logo.png',       # Logo 16/9 in bottom right of header
    )

    print( f"Invoice metadata: {metadata}" )
    temp		= Path( tmp_path )
    path		= temp / 'invoice-complete.pdf'
    pdf.output( path )
    print( f"Invoice saved: {path}" )


# Generate a sequence of Invoices w/ unique accounts
with open( '/usr/share/dict/words', 'r' ) as words_f:
    words		= list(
        w.strip() for w in words_f.readlines()
    )


line_currencies		= [
    "Bitcoin",
    "BTC",
    "Ethereum",
    "ETH",
    "DAI",
    None,
    "USDC",
    "USDT",
    "US Dollar",
    "XRP",
    "HOT",
    "Shiba Inu",
    "ZEENUS",  # Worthless; will cause Invoice to fail if chosen as one of payment 'currencies'
]


def line( i, most=None, seen=None ):
    # Sorted from least to most valuable, so c_offset reduces price of items w/ higher-valued currencies
    c_i				= random.randint( 0, len( line_currencies ) - 1 )  # Index eg. [0,12]
    currency			= line_currencies[c_i]
    if most and seen is not None:
        if len( seen ) < most:
            seen.add( currency )
            log.info( f"Invoice line-items contain only currencies {commas( seen, final='and' )}" )
        else:
            currency		= random.choice( tuple( seen ))
            c_i			= line_currencies.index( currency )

    c_offset			= int( round( math.sqrt( c_i )))		# [0,4]

    return LineItem(
        description	= ' '.join(
            random.choice( words )
            for _ in range( random.randint( 1, 5 ))
        ).capitalize(),
        units		= random.randint( 0, 100 ),
        price		= round( random.random(), random.randint( 0, 6 )) * 10 ** ( c_offset - random.randint( 0, 5 )),
        currency	= currency,
        tax		= random.choice( [0, 1] ) + random.randint( 0, 20 ) / 100,
    )


def items( n, most=None, seen=None ):
    if most and seen is None:
        seen			= set()
    for i in range( n ):
        yield line( i, most=most, seen=seen )


conversions			= {
    ("BTC","XRP"): 60000,
}

desired			= 10
paths			= f"../-{desired - 1}"

invoices_to_write		= [
    [
        # - No obvious route between line-item currencies, and invoice currency:
        #
        # Only XRP LineItems, want USDC in 'currencies' payable (as well as 'BTC', 'ETH' and
        # 'XRP' accounts) -- but only {('XRP','BTC'): <ratio>} conversion provided.  Must deduce
        # a common currency for computing remaining conversions ratios, but must include
        # ('BTC',<something>).
        Invoice(
            items( random.randint( 1, 100 ), most=1, seen=set( ('XRP', ) )),
            accounts	= [
                account( SEED_ZOOS, crypto='Ethereum' ),
                account( SEED_ZOOS, crypto='Bitcoin' ),
                account( SEED_ZOOS, crypto='Ripple' ),
            ],
            currencies	= ['USDC'],
            conversions	= dict( conversions ) #  | {('BTC','ETH'): None}, # now automatic
        )
    ],
    (
        # - Random combinations of LineItem / Invoice currencies
        #
        # A sequence (generator) of Invoices w/ random LineItems, over a sequence of 'desired'
        # accounts Only 1-3 different cryptos on line-items, 1-3 other invoice currencies each
        # invoice, and 3 Crypto accounts (only 9 cryptocurrencies will typically fit in the
        # conversions table).
        Invoice(
            items( random.randint( 1, 100 ), most=random.randint( 1, 3 )),
            accounts	= a,
            currencies	= list( random.choice( line_currencies ) for _ in range( random.randint( 0, 2 ))) or None,
            conversions	= dict( conversions ),
        )
        for a in zip(
            accounts( SEED_ZOOS, crypto='Ethereum', paths=paths ),
            accounts( SEED_ZOOS, crypto='Bitcoin', paths=paths ),
            accounts( SEED_ZOOS, crypto='Ripple', paths=paths ),
        )
    ),
]


@pytest.mark.parametrize( "invoices", invoices_to_write )
def test_write_invoices( tmp_path, invoices ):
    directory		= Path( tmp_path )
    print( f"Invoice Output path: {directory}" )

    metadata		= InvoiceMetadata(
        client		= client,
        vendor		= vendor,
        directory	= directory,
    )

    i				= None
    try:
        for i,(name, output) in enumerate( write_invoices(
            ( (invoice,metadata) for invoice in invoices )
        )):
            print( f"{ordinal( i )} Invoice {name}: {output}" )
    except Exception as exc:
        # Only certain failures are allowed/expected:
        # - Selecting a zero-value Cryptocurrency as a payment currency
        exc_str			= str( exc )
        if "Failed to resolve conversion ratios" in exc_str:
            assert 'EENUS' in exc_str
            log.warning( "Stopped due to selecting zero-valued crypto as payment currency" )
        else:
            raise
