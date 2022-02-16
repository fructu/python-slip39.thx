import ast
import io
import os
import json
import logging
import math

from datetime		import datetime
from collections	import namedtuple
from collections.abc	import Callable

from typing		import Dict, List, Tuple, Sequence
import qrcode
from fpdf		import FPDF, FlexTemplate

from .			import Account
from .api		import create, enumerate_mnemonic, group_parser
from .util		import input_secure, ordinal
from .defaults		import (
    FONTS, MNEM_ROWS_COLS, CARD, CARD_SIZES, PAPER, PAGE_MARGIN, WALLET, WALLET_SIZES, COLOR,
    GROUPS, GROUP_THRESHOLD_RATIO,
    FILENAME_FORMAT,
    CRYPTO_PATHS,
)

# Optionally support output of encrypted JSON files
eth_account			= None
try:
    import eth_account
except ImportError:
    pass

log				= logging.getLogger( __package__ )


class Region:
    """Takes authority for a portion of another Region, and places things in it, relative to its
    upper-left and lower-right corners."""
    def __init__( self, name, x1=None, y1=None, x2=None, y2=None, rotate=None ):
        self.name		= name
        self.x1			= x1		# could represent positions, offsets or ratios
        self.y1			= y1
        self.x2			= x2
        self.y2			= y2
        self.rotate		= rotate
        self.regions		= []

    def element( self ):
        "Converts to mm."
        return dict(
            name	= self.name,
            x1		= self.x1 * 25.4,
            y1		= self.y1 * 25.4,
            x2		= self.x2 * 25.4,
            y2		= self.y2 * 25.4,
            rotate	= self.rotate or 0.0
        )

    def __str__( self ):
        return f"({self.name:16}: ({float(self.x1):8}, {float( self.y1):8}) - ({float(self.x2):8} - {float(self.y2):8})"

    def add_region( self, region ):
        region.x1		= self.x1 if region.x1 is None else region.x1
        region.y1		= self.y1 if region.y1 is None else region.y1
        region.x2		= self.x2 if region.x2 is None else region.x2
        region.y2		= self.y2 if region.y2 is None else region.y2

        self.regions.append( region )
        return region

    def add_region_relative( self, region ):
        region.x1	       += self.x1
        region.y1	       += self.y1
        region.x2	       += self.x2
        region.y2	       += self.y2
        self.regions.append( region )
        return region

    def add_region_proportional( self, region ):
        region.x1		= self.x1 + ( self.x2 - self.x1 ) * ( 0 if region.x1 is None else region.x1 )
        region.y1		= self.y1 + ( self.y2 - self.y1 ) * ( 0 if region.y1 is None else region.y1 )
        region.x2		= self.x1 + ( self.x2 - self.x1 ) * ( 1 if region.x2 is None else region.x2 )
        region.y2		= self.y1 + ( self.y2 - self.y1 ) * ( 1 if region.y2 is None else region.y2 )
        self.regions.append( region )
        return region

    def dimensions( self ):
        "Converts to mm."
        return Coordinate( (self.x2 - self.x1) * 25.4, (self.y2 - self.y1) * 25.4 )

    def elements( self ):
        """Yield a sequence of { 'name': "...", 'x1': #,  ... }"""
        if self.__class__ != Region:
            yield self.element()
        for r in self.regions:
            for d in r.elements():
                yield d


class Text( Region ):
    SIZE_RATIO			= 3/4

    def __init__( self, *args, font=None, text=None, size=None, size_ratio=None, align=None,
                  foreground=None, background=None, bold=None, italic=None, underline=None,
                  **kwds ):
        self.font		= font
        self.text		= text
        self.size		= size
        self.size_ratio		= size_ratio or self.SIZE_RATIO
        self.align		= align
        self.foreground		= foreground
        self.background		= background
        self.bold		= bold
        self.italic		= italic
        self.underline		= underline
        super().__init__( *args, **kwds )

    def element( self ):
        d			= super().element()
        d['type']		= 'T'
        d['font']		= FONTS.get( self.font ) or self.font or FONTS.get( 'sans' )
        line_height		= (self.y2 - self.y1) * 72  # Postscript point == 1/72 inch
        d['size']		= self.size or ( line_height * self.size_ratio )  # No need for int(round(..))
        if self.text is not None:
            d['text']		= self.text
        if self.bold:
            d['bold']		= True
        if self.italic:
            d['italic']		= True
        if self.underline:
            d['underline']	= True
        if self.align is not None:
            d['align']		= self.align
        if self.foreground is not None:
            d['foreground']	= self.foreground
        if self.background is not None:
            d['background']	= self.background
        return d


class Image( Region ):
    def __init__( self, *args, font=None, text=None, size=None, **kwds ):
        self.font		= font
        self.text		= text
        self.size		= None
        super().__init__( *args, **kwds )

    def element( self ):
        d			= super().element()
        d['type']		= 'I'
        return d


class Line( Region ):
    def emit( self, d, *args, **kwds ):
        d['type']		= 'L'
        super().emit( *args, **kwds )


class Box( Region ):
    def element( self ):
        d			= super().element()
        d['type']		= 'B'
        return d


Coordinate			= namedtuple( 'Coordinate', ('x', 'y') )


def layout_card(
    card_size: Coordinate,
    card_margin: int,
    num_mnemonics: int	= 20,
):
    card			= Box( 'card', 0, 0, card_size.x, card_size.y )
    card_interior		= card.add_region_relative(
        Region( 'card-interior', x1=+card_margin, y1=+card_margin, x2=-card_margin, y2=-card_margin )
    )
    for c_n in range( 16 ):  # SLIP-39 supports up to 16 groups
        card_interior.add_region_proportional(
            Text( f'card-g{c_n}', x1=1/8, y1=-1/16, x2=7/8, y2=5/16, foreground=int( COLOR[c_n % len( COLOR )], 16 ), rotate=-45 )
        )
    card_top			= card_interior.add_region_proportional(
        Region( 'card-top', x1=0, y1=0, x2=1, y2=1/4 )
    )
    card_bottom			= card_interior.add_region_proportional(
        Region( 'card-bottom', x1=0, y1=1/4, x2=1, y2=1 )
    )
    card_mnemonics		= card_bottom.add_region_proportional(
        Region( 'card-mnemonics', x1=0, y1=0, x2=13/16, y2=1 )
    )
    card_qr1			= card_bottom.add_region_proportional(
        Image( 'card-qr1', x1=13/16, y1=0, x2=1, y2=1/2 )
    )
    card_qr1.y2			= card_qr1.y1 + (card_qr1.x2 - card_qr1.x1)  # make height same as width

    card_qr2			= card_bottom.add_region_proportional(
        Image( 'card-qr2', x1=13/16, y1=1/2, x2=1, y2=1 )
    )
    card_qr2.y1			= card_qr2.y2 - (card_qr2.x2 - card_qr2.x1)  # make height same as width

    card_top.add_region_proportional(
        Text( 'card-title', x1=0, y1=0, x2=1, y2=40/100, bold=True )
    )
    card_top.add_region_proportional(
        Text( 'card-requires', x1=0, y1=40/100, x2=1, y2=66/100, align='C', italic=True )
    )
    card_top.add_region_proportional(
        Text( 'card-crypto1', x1=0, y1=66/100, x2=1, y2=83/100, align='R' )
    )
    card_top.add_region_proportional(
        Text( 'card-crypto2', x1=0, y1=83/100, x2=1, y2=100/100, align='R' )
    )

    assert num_mnemonics in MNEM_ROWS_COLS, \
        f"Invalid SLIP-39 mnemonic word count: {num_mnemonics}"
    rows,cols		= MNEM_ROWS_COLS[num_mnemonics]
    for r in range( rows ):
        for c in range( cols ):
            card_mnemonics.add_region_proportional(
                Text(
                    f"mnem-{c * rows + r}",
                    x1		= c/cols,
                    y1		= r/rows,
                    x2		= (c+1)/cols,
                    y2		= (r+1)/rows,
                    font	= 'mono',
                    size_ratio	= 9/16,
                )
            )
    return card


def layout_wallet(
    wallet_size: Coordinate,
    wallet_margin: int,
):
    """Produce a template format for a Paper Wallet.  """
    wallet			= Box( 'wallet', 0, 0, wallet_size.x, wallet_size.y )
    wallet_background		= wallet.add_region_proportional(  # noqa: F841
        Image( 'wallet-bg' ),
    )

    # Most of the Paper Wallet is visible (contains public address information).  The right-most
    # portion can be folded over, and displays private key information
    show			= wallet.add_region_proportional(
        Region( 'wallet-show', x2=5/8 )
    )
    fold			= wallet.add_region_proportional(
        Region( 'wallet-fold', x1=5/8 )
    )

    public			= show.add_region_relative(
        Box( 'wallet-public', x1=+wallet_margin, y1=+wallet_margin, x2=-wallet_margin, y2=-wallet_margin )
    )
    private			= fold.add_region_relative(
        Box( 'wallet-private', x1=+wallet_margin, y1=+wallet_margin, x2=-wallet_margin, y2=-wallet_margin )
    )

    # Assign each different Crypto name a different color, in template labels crypto-{f,b}1, crypto-{f,b}2, ...
    for c_n in range( len( COLOR )):
        public.add_region_proportional(
            Text( f'crypto-f{c_n}', x1=1/8, y1=-1/16, x2=7/8, y2=7/16, foreground=int( COLOR[c_n], 16 ), rotate=-45 )
        )
        private.add_region_proportional(
            Text( f'crypto-b{c_n}', x1=2/8, y1=-1/16, x2=7/8, y2=7/16, foreground=int( COLOR[c_n], 16 ), rotate=-45 )
        )

    # Public addresses are vertical on left- and right-hand of public Region.  In order to fit the
    # longer ETH addresses into a space with a fixed-width font, we know that the ratio of the width
    # to the height has to be about 1/20.  Rotation is downward around upper-left corner; so,
    # lower-left corner will shift 1 height leftward and upward; so start 1 height right and down.
    address_length		= public.y2 - public.y1
    address_height		= address_length * 1/20
    public.add_region(
        Image(
            'address-l-bg',
            x1		= public.x1 + address_height,
            y1		= public.y1,
            x2		= public.x1 + address_height + address_length,
            y2		= public.y1 + address_height,
            rotate	= -90,
        )
    ).add_region(
        Text(
            'address-l',
            font	= 'mono',
            rotate	= -90,
        )
    )

    # Rotation is upward around the upper-left corner, so lower-left corner will shift 1 height
    # upward and right; so start 1 height leftward and down.
    public.add_region(
        Image(
            'address-r-bg',
            x1		= public.x2 - address_height,
            y1		= public.y2,
            x2		= public.x2 - address_height + address_length,
            y2		= public.y2 + address_height,
            rotate	= +90,
        )
    ).add_region(
        Text(
            'address-r',
            font	= 'mono',
            rotate	= +90,
        )
    )

    # Make Public QR Code square w/ min of height, width, anchored at lower-left corner
    public.add_region_proportional(
        Text( 'address-qr-t',	x1=1/16, y1=5/16, x2=1, y2=6/16 )
    )
    public_qr			= public.add_region_proportional(
        Image( 'address-qr', 	x1=1/16, y1=6/16, x2=1, y2=15/16 )
    )
    public_qr_size		= min( public_qr.x2 - public_qr.x1, public_qr.y2 - public_qr.y1 )
    public_qr.x2		= public_qr.x1 + public_qr_size
    public_qr.y1		= public_qr.y2 - public_qr_size
    public.add_region_proportional(
        Text( 'address-qr-b',	x1=1/16, y1=15/16, x2=1, y2=16/16 )
    )

    # Private region

    private.add_region_proportional(
        Text( 'private-qr-t',	x1=0/16, y1=5/16, x2=1, y2=6/16 )
    )
    private_qr			= private.add_region_proportional(
        Image( 'private-qr',	x1=0/16, y1=6/16, x2=1, y2=15/16 )
    )
    private_qr_size		= min( private_qr.x2 - private_qr.x1, private_qr.y2 - private_qr.y1 )
    private_qr.x2		= private_qr.x1 + private_qr_size
    private_qr.y1		= private_qr.y2 - private_qr_size
    private.add_region_proportional(
        Text( 'private-qr-b',	x1=0/16, y1=15/16, x2=1, y2=16/16 )
    )

    # Hint above; but same computed width as private_qr
    private_h_t			= private.add_region_proportional(
        Text( 'private-hint-t',	x1=0/16, y1=0/16, x2=1, y2=1/16 )
    )
    private_h_t.x2		= private_qr.x2
    private_h_bg		= private.add_region_proportional(
        Image( 'private-hint-bg',x1=0/16, y1=1/16, x2=1, y2=4/16 )
    )
    private_h_bg.x2		= private_qr.x2
    private_h			= private.add_region_proportional(
        Text( 'private-hint',	x1=0/16, y1=1/16, x2=1, y2=3/16 )
    )
    private_h.x2		= private_qr.x2

    # We'll use the right side of the private region, each line rotated 90 degrees down and right.
    # So, we need the upper-left corner of the private-bg anchored at the upper-right corner of
    # private.
    private_length		= private.y2 - private.y1       # line length is y-height
    private_fontsize		= 6.8				# points == 1/72 inch
    private_height		= private.x2 - private_qr.x2 - .05
    private_lineheight		= private_fontsize / 72 / Text.SIZE_RATIO * .9  # in.

    private.add_region(
        Image(
            'private-bg',
            x1		= private.x2,
            y1		= private.y1,
            x2		= private.x2 + private_length,
            y2		= private.y1 + private_height,
            rotate	= -90,
        )
    )
    # Now, add private key lines down the edge from right to left, rotating each into place
    for ln in range( int( private_height // private_lineheight )):
        private.add_region(
            Text(
                f"private-{ln}",
                font	= 'mono',
                x1	= private.x2 - private_lineheight * ln,
                y1	= private.y1,
                x2	= private.x2 + private_length,
                y2	= private.y1 + private_lineheight,
                size	= private_fontsize,
                rotate	= -90,
            )
        )

    return wallet


def layout_components(
    pdf: FPDF,
    comp_dim: Coordinate,
    page_margin_mm: float	= .25 * 25.4,   # 1/4" in mm.
) -> Tuple[int, Callable[[int],[int, Coordinate]]]:
    """Compute the number of components per pdf page, and a function returning the page # and
    component (x,y) for the num'th component."""

    # FPDF().epw/.eph is *without* page margins, but *with* re-orienting for portrait/landscape
    # Allow 5% bleed over into page margins (to allow for slight error in paper vs. comp sizes)
    comp_cols			= int(( pdf.epw - page_margin_mm * 2 * 95/100 ) // comp_dim.x )
    comp_rows			= int(( pdf.eph - page_margin_mm * 2 * 95/100 ) // comp_dim.y )
    comps_pp			= comp_rows * comp_cols

    def page_xy( num ):
        """Returns the page, and the coordinates within that page of the num'th component"""
        page,nth		= divmod( num, comps_pp )
        page_rows,page_cols	= divmod( nth, comp_cols )
        offsetx			= page_margin_mm + page_cols * comp_dim.x
        offsety			= page_margin_mm + page_rows * comp_dim.y
        log.debug( f"{ordinal(num)} {comp_dim.x:7.5f}mm x {comp_dim.y:7.5f}mm component on page {page}, offset {offsetx:7.5f}mm x {offsety:7.5f}mm" )
        return (page, Coordinate( x=offsetx, y=offsety ))

    return (comps_pp, page_xy)


def layout_pdf(
        card_dim: Coordinate,                   # mm.
        page_margin_mm: float	= .25 * 25.4,   # 1/4" in mm.
        orientation: str	= 'portrait',
        paper_format: str	= 'Letter'
) -> Tuple[int, Callable[[int],[int, Coordinate]], FPDF, str]:
    """Find the ideal orientation for the most cards of the given dimensions.  Returns the number of
    cards per page, the FPDF, and a function useful for laying out templates on the pages of the
    PDF."""
    pdf				= FPDF(
        orientation	= orientation,
        format		= paper_format,
    )
    pdf.set_margin( 0 )

    return layout_components(
        pdf, comp_dim=card_dim, page_margin_mm=page_margin_mm
    ) + (pdf, orientation)


def output_pdf(
    name: str,
    group_threshold: int,
    groups: Dict[str,Tuple[int,List[str]]],
    accounts: Sequence[Sequence[Account]],
    card_format: str		= CARD,   # 'index' or '(<h>,<w>),<margin>'
    paper_format: str		= PAPER,  # 'Letter', ...
) -> Tuple[FPDF, Sequence[Sequence[Account]]]:
    """Produces a PDF, containing a number of cards containing the provided slip39.Details if
    card_format is not False, and pass through the supplied accounts."""

    # Deduce the card size
    try:
        (card_h,card_w),card_margin = CARD_SIZES[card_format.lower()]
    except KeyError:
        (card_h,card_w),card_margin = ast.literal_eval( card_format )
    card_size			= Coordinate( y=card_h, x=card_w )

    # Compute how many cards per page.  Flip page portrait/landscape to match the cards'.  Use the length
    # of the first Group's first Mnemonic to determine the number of mnemonics on each card.
    num_mnemonics		= len( groups[next(iter(groups.keys()))][1][0].split() )
    card			= layout_card(  # converts to mm
        card_size, card_margin, num_mnemonics=num_mnemonics )
    card_dim			= card.dimensions()

    # Find the best PDF and orientation, by max of returned cards_pp (cards per page)
    page_margin_mm		= PAGE_MARGIN * 25.4
    cards_pp,page_xy,pdf,orientation = max(
        layout_pdf( card_dim, page_margin_mm, orientation=orientation, paper_format=paper_format )
        for orientation in ('portrait', 'landscape')
    )
    log.debug( f"Page: {paper_format} {orientation} {pdf.epw:.8}mm w x {pdf.eph:.8}mm h w/ {page_margin_mm}mm margins,"
               f" Card: {card_format} {card_dim.x:.8}mm w x {card_dim.y:.8}mm h == {cards_pp} cards/page" )

    elements			= list( card.elements() )
    if log.isEnabledFor( logging.DEBUG ):
        log.debug( f"Card elements: {json.dumps( elements, indent=4)}" )
    tpl				= FlexTemplate( pdf, list( card.elements() ))

    group_reqs			= list(
        f"{g_nam}({g_of}/{len(g_mns)})" if g_of != len(g_mns) else f"{g_nam}({g_of})"
        for g_nam,(g_of,g_mns) in groups.items() )
    requires			= f"Recover w/ {group_threshold} of {len(group_reqs)} groups {', '.join(group_reqs[:4])}{'...' if len(group_reqs)>4 else ''}"

    # Convert all of the first group's account(s) to an address QR code
    assert accounts and accounts[0], \
        "At least one cryptocurrency account must be supplied"
    qr				= {}
    for i,acct in enumerate( accounts[0] ):
        qrc			= qrcode.QRCode(
            version	= None,
            error_correction = qrcode.constants.ERROR_CORRECT_M,
            box_size	= 10,
            border	= 0
        )
        qrc.add_data( acct.address )
        qrc.make( fit=True )

        qr[i]			= qrc.make_image()
        if log.isEnabledFor( logging.INFO ):
            f			= io.StringIO()
            qrc.print_ascii( out=f )
            f.seek( 0 )
            for line in f:
                log.info( line.strip() )

    card_n			= 0
    page_n			= None
    for g_n,(g_name,(g_of,g_mnems)) in enumerate( groups.items() ):
        for mn_n,mnem in enumerate( g_mnems ):
            p,(offsetx,offsety)	= page_xy( card_n )
            if p != page_n:
                pdf.add_page()
                page_n		= p
            card_n	       += 1

            tpl['card-title']	= f"SLIP39 {g_name}({mn_n+1}/{len(g_mnems)}) for: {name}"
            tpl['card-requires'] = requires
            tpl['card-crypto1']	= f"{accounts[0][0].crypto} {accounts[0][0].path}: {accounts[0][0].address}"
            tpl['card-qr1']	= qr[0].get_image()
            if len( accounts[0] ) > 1:
                tpl['card-crypto2'] = f"{accounts[0][1].crypto} {accounts[0][1].path}: {accounts[0][1].address}"
                tpl['card-qr2']	= qr[1].get_image()
            tpl[f'card-g{g_n}']	= f"{g_name:6.6}..{mn_n+1}" if len(g_name) > 7 else f"{g_name} {mn_n+1}"

            for n,m in enumerate_mnemonic( mnem ).items():
                tpl[f"mnem-{n}"] = m

            tpl.render( offsetx=offsetx, offsety=offsety )

    return pdf,accounts


def write_pdfs(
    names		= None,		# sequence of [ <name>, ... ], or { "<name>": <details> }
    master_secret	= None,
    passphrase		= None,		# UTF-8 encoded passphrase; default is '' (empty)
    group		= None,		# Group specifications, [ "Frens(3/6)", ... ]
    threshold		= None,		# int, or 1/2 of groups by default
    cryptocurrency	= None,		# sequence of [ 'ETH:<path>', ... ] to produce accounts for
    card		= None,		# False outputs no PDF
    paper		= None,
    filename		= None,
    json_pwd		= None,		# If JSON wallet output desired, supply password
    text		= None,		# Truthy outputs SLIP-39 recover phrases to stdout
    wallet_pwd		= None,		# If paper wallet images desired, supply password
    wallet_pwd_hint	= None,		# an optional password hint
    wallet_format	= None,		# and a paper wallet format (eg. 'third')
):
    """Writes a PDF containing a unique SLIP-39 encoded seed for each of the names specified.

    Returns a { "<filename>": <details>, ... } dictionary of all PDF files written, and each of
    their account details.

    """

    # Convert sequence of group specifications into standard { "<group>": (<needs>, <size>) ... }
    if isinstance( group, dict ):
        groups			= group
    else:
        groups			= dict(
            group_parser( g )
            for g in group or GROUPS
        )
    assert groups and all( isinstance( k, str ) and len( v ) == 2 for k,v in groups.items() ), \
        f"Each group member specification must be a '<group>': (<needs>, <size>), not {type(next(groups.items()))}"

    group_threshold		= int( threshold ) if threshold else math.ceil( len( groups ) * GROUP_THRESHOLD_RATIO )

    cryptopaths			= []
    for crypto in cryptocurrency or CRYPTO_PATHS:
        try:
            if isinstance( crypto, str ):
                crypto,paths	= crypto.split( ':' )   # Find the  <crypto>,<path> tuple
            else:
                crypto,paths	= crypto		# Already a <crypto>,<path> tuple?
        except ValueError:
            crypto,paths	= crypto,None
        cryptopaths.append( (crypto,paths) )

    # If account details not provided in names, generate them.
    if not isinstance( names, dict ):
        assert not master_secret or not names or len( names ) == 1, \
            "Creating multiple account details from the same secret entropy doesn't make sense"
        names			= {
            name: create(
                name		= name,
                group_threshold	= group_threshold,
                groups		= groups,
                master_secret	= master_secret,
                passphrase	= passphrase.encode( 'utf-8' ) if passphrase else b'',
                cryptopaths	= cryptopaths,
            )
            for name in names or [ "SLIP39" ]
        }

    # Generate each desired SLIP-39 wallet file.  Supports --card (the default).
    results			= {}
    for name, details in names.items():
        # Get the first group of the accountgroups in details.accounts.
        accounts		= details.accounts
        assert accounts and accounts[0], \
            "At least one --cryptocurrency must be specified"
        for account in accounts[0]:
            log.warning( f"{account.crypto:6} {account.path:20}: {account.address}" )

        if text:
            # Output the SLIP-39 mnemonics as text:
            #    name: mnemonic
            for g_name,(g_of,g_mnems) in details.groups.items():
                for mnem in g_mnems:
                    print( f"{name}{name and ': ' or ''}{mnem}" )

        # Unless no card or paper wallets specified, output a PDF containing the SLIP-39 mnemonic recovery cards
        pdf			= None
        if card is not False or wallet_pwd:
            pdf,_		= output_pdf(
                *details,
                card_format	= card or CARD,
                paper_format	= paper or PAPER )

        now			= datetime.now()

        pdf_name		= ( filename or FILENAME_FORMAT ).format(
            name	= name,
            date	= datetime.strftime( now, '%Y-%m-%d' ),
            time	= datetime.strftime( now, '%H.%M.%S'),
            crypto	= accounts[0][0].crypto,
            path	= accounts[0][0].path,
            address	= accounts[0][0].address,
        )
        if not pdf_name.lower().endswith( '.pdf' ):
            pdf_name	       += '.pdf'

        if wallet_pwd:
            # Deduce the paper wallet size and create a template.  All layouts are in specified in
            # inches; template dimensions are in mm.
            try:
                (wall_h,wall_w),wall_margin = WALLET_SIZES[wallet_format.lower() if wallet_format else WALLET]
            except KeyError:
                (wall_h,wall_w),wall_margin = ast.literal_eval( wallet_format )
            log.warning( f"Producing {wall_w:.3f}in x {wall_h:.3f}in Paper Wallets" )
            wall		= layout_wallet( Coordinate( y=wall_h, x=wall_w ), wall_margin )  # converts to mm
            wall_dim		= wall.dimensions()

            # Lay out wallets, always in Portrait orientation
            pdf.add_page( orientation='P' )
            page_margin_mm	= PAGE_MARGIN * 25.4

            walls_pp,page_xy	= layout_components( pdf, comp_dim=wall_dim, page_margin_mm=page_margin_mm )
            elements		= list( wall.elements() )
            if log.isEnabledFor( logging.DEBUG ):
                log.debug( f"Wallet elements: {json.dumps( elements, indent=4)}" )
            wall_tpl		= FlexTemplate( pdf, elements )

            # Place each Paper Wallet adding pages as necessary (we already have the first fresh page).
            wall_n		= 0
            page_n		= 0
            for account_group in accounts:
                for c_n,account in enumerate( account_group ):
                    p,(offsetx,offsety) = page_xy( wall_n )
                    if p != page_n:
                        pdf.add_page( orientation='P' )
                        page_n	= p
                    try:
                        private_enc		= account.encrypted( 'password' )
                    except NotImplementedError as exc:
                        log.exception( f"{account.crypto} doesn't support BIP-38 or JSON wallet encryption: {exc}" )
                        continue

                    wall_n     += 1
                    log.info( f"{ordinal( wall_n ):5} {account.crypto} Paper Wallet at {offsetx:5},{offsety:5}" )

                    images			= os.path.join( os.path.dirname( __file__ ), '..', 'images' )
                    wall_tpl['wallet-bg']	= os.path.join( images, 'paper-wallet-background.png' )
                    wall_tpl[f"crypto-f{c_n}"]	= account.crypto
                    wall_tpl[f"crypto-b{c_n}"]	= account.crypto

                    public_qr	= qrcode.QRCode(
                        version		= None,
                        error_correction = qrcode.constants.ERROR_CORRECT_M,
                        box_size	= 10,
                        border		= 1,
                    )
                    public_qr.add_data( account.address )
                    wall_tpl['address-l-bg']	= os.path.join( images, '1x1-ffffff7f.png' )
                    wall_tpl['address-l']	= account.address
                    wall_tpl['address-r-bg']	= os.path.join( images, '1x1-ffffff7f.png' )
                    wall_tpl['address-r']	= account.address
                    wall_tpl['address-qr-t']	= 'PUBLIC ADDRESS'
                    wall_tpl['address-qr']	= public_qr.make_image( back_color="transparent" ).get_image()
                    wall_tpl['address-qr-b']	= 'DEPOSIT/VERIFY'

                    private_qr	= qrcode.QRCode(
                        version		= None,
                        error_correction = qrcode.constants.ERROR_CORRECT_M,
                        box_size	= 10,
                        border		= 1,
                    )
                    private_qr.add_data( private_enc )

                    wall_tpl['private-bg']	= os.path.join( images, '1x1-ffffff7f.png' )

                    def chunker( sequence, size ):
                        while sequence:
                            yield sequence[:size]
                            sequence		= sequence[size:]

                    # If not enough lines, will throw Exception, as it should!  We don't want
                    # to emit a Paper Wallet without the entire encrypted private key present.
                    for ln,line in enumerate( chunker( private_enc, 40 )):
                        wall_tpl[f"private-{ln}"] = line
                    wall_tpl['private-hint-t']	= 'PASSPHRASE HINT:'
                    wall_tpl['private-hint-bg']	= os.path.join( images, '1x1-ffffff7f.png' )
                    wall_tpl['private-hint']	= wallet_pwd_hint
                    wall_tpl['private-qr-t']	= 'PRIVATE KEY'
                    wall_tpl['private-qr']	= private_qr.make_image( back_color="transparent" ).get_image()
                    wall_tpl['private-qr-b']	= 'SPEND'

                    wall_tpl.render( offsetx=offsetx, offsety=offsety )

        if json_pwd:
            # If -j|--json supplied, also emit the encrypted JSON wallet.  This may be a *different*
            # password than the SLIP-39 master secret encryption passphrase.  It will be required to
            # decrypt and use the saved JSON wallet file, eg. to load a software Ethereum wallet.
            assert eth_account, \
                "The optional eth-account package is required to support output of encrypted JSON wallets\n" \
                "    python3 -m pip install eth-account"
            assert any( 'ETH' == crypto for crypto,paths in cryptopaths ), \
                "--json is only valid if '--crypto ETH' wallets are specified"
            if json_pwd == '-':
                json_pwd	= input_secure( 'JSON key file password: ', secret=True )
            else:
                log.warning( "It is recommended to not use '-j|--json <password>'; specify '-' to read from input" )

            for eth in (
                account
                for group in accounts
                for account in group
                if account.crypto == 'ETH'
            ):
                json_str	= json.dumps( eth_account.Account.encrypt( eth.key, json_pwd ), indent=4 )
                json_name	= ( filename or FILENAME_FORMAT ).format(
                    name	= name or "SLIP39",
                    date	= datetime.strftime( now, '%Y-%m-%d' ),
                    time	= datetime.strftime( now, '%H.%M.%S'),
                    crypto	= eth.crypto,
                    path	= eth.path,
                    address	= eth.address,
                )
                if json_name.lower().endswith( '.pdf' ):
                    json_name	= json_name[:-4]
                json_name      += '.json'
                while os.path.exists( json_name ):
                    log.error( "ERROR: Will NOT overwrite {json_name}; adding '.new'!" )
                    json_name  += '.new'
                with open( json_name, 'w' ) as json_f:
                    json_f.write( json_str )
                log.warning( f"Wrote JSON {name or 'SLIP39'}'s encrypted ETH wallet {eth.address} derived at {eth.path} to: {json_name}" )

                if pdf:
                    # Add the encrypted JSON account recovery to the PDF also, if generated.
                    pdf.add_page()
                    margin_mm	= PAGE_MARGIN * 25.4
                    pdf.set_margin( 1.0 * 25.4 )

                    col_width	= pdf.epw - 2 * margin_mm
                    pdf.set_font( FONTS['sans'], size=10 )
                    line_height	= pdf.font_size * 1.2
                    pdf.cell( col_width, line_height, json_name )
                    pdf.ln( line_height )

                    pdf.set_font( FONTS['sans'], size=9 )
                    line_height	= pdf.font_size * 1.1

                    for line in json_str.split( '\n' ):
                        pdf.cell( col_width, line_height, line )
                        pdf.ln( line_height )
                    pdf.image( qrcode.make( json_str ).get_image(), h=min(pdf.eph, pdf.epw)/2, w=min(pdf.eph, pdf.epw)/2 )

        if pdf:
            pdf.output( pdf_name )
            log.warning( f"Wrote SLIP39-encoded wallet for {name!r} to: {pdf_name}" )
        results[pdf_name]	= details

    return results
