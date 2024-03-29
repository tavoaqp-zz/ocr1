################################################################
### common functions for data structures, file name manipulation, etc.
################################################################

import os,os.path,re,numpy,unicodedata,sys,warnings,inspect,glob,traceback
import numpy
from numpy import *
from scipy.misc import imsave
from scipy.ndimage import interpolation, measurements, morphology, filters

import improc
import ligatures
import sl
import multiprocessing

import cPickle as pickle
from pylab import imshow
import psegutils
from pylab import imshow
import psegutils,morph
from toplevel import *

pickle_mode = 2

def deprecated(f):
    def _wrap(f):
        warned = 0
        def _wrapper(*args,**kw):
            if not warned:
                print f,"has been DEPRECATED"
                warned = 1
            return f(*args,**kw)
    return _wrap



################################################################
### Text I/O
################################################################

import codecs

def read_text(fname,nonl=1):
    with codecs.open(fname,"r","utf-8") as stream:
        result = stream.read()
    if nonl and len(result)>0 and result[-1]=='\n':
        result = result[:-1]
    return result

def write_text(fname,text,nonl=0):
    with codecs.open(fname,"w","utf-8") as stream:
        stream.write(text)
        if not nonl and text[-1]!='\n':
            stream.write('\n')

################################################################
### Image I/O
################################################################

import PIL

def pil2array(im,alpha=0):
    if im.mode=="L":
        a = numpy.fromstring(im.tostring(),'B')
        a.shape = im.size[1],im.size[0]
        return a
    if im.mode=="RGB":
        a = numpy.fromstring(im.tostring(),'B')
        a.shape = im.size[1],im.size[0],3   
        return a
    if im.mode=="RGBA":
        a = numpy.fromstring(im.tostring(),'B')
        a.shape = im.size[1],im.size[0],4
        if not alpha: a = a[:,:,:3]
        return a
    return pil2array(im.convert("L"))

def array2pil(a):
    if a.dtype==dtype("B"):
        if a.ndim==2:
            return PIL.Image.fromstring("L",(a.shape[1],a.shape[0]),a.tostring())
        elif a.ndim==3:
            return PIL.Image.fromstring("RGB",(a.shape[1],a.shape[0]),a.tostring())
        else:
            raise Exception("bad image rank")
    elif a.dtype==dtype('float32'):
        return PIL.Image.fromstring("F",(a.shape[1],a.shape[0]),a.tostring())
    else:
        raise Exception("unknown image type")

def isbytearray(a):
    return a.dtype in [dtype('uint8')]

def isfloatarray(a):
    return a.dtype in [dtype('f'),dtype('float32'),dtype('float64')]

def isintarray(a):
    return a.dtype in [dtype('B'),dtype('int16'),dtype('int32'),dtype('int64'),dtype('uint16'),dtype('uint32'),dtype('uint64')]

def isintegerarray(a):
    return a.dtype in [dtype('int32'),dtype('int64'),dtype('uint32'),dtype('uint64')]

@checks(str,pageno=int,_=GRAYSCALE)
def read_image_gray(fname,pageno=0):
    """Read an image and returns it as a floating point array.
    The optional page number allows images from files containing multiple
    images to be addressed.  Byte and short arrays are rescaled to
    the range 0...1 (unsigned) or -1...1 (signed)."""
    if type(fname)==tuple: fname,pageno = fname
    assert pageno==0
    pil = PIL.Image.open(fname)
    a = pil2array(pil)
    if a.dtype==dtype('uint8'):
        a = a/255.0
    if a.dtype==dtype('int8'):
        a = a/127.0
    elif a.dtype==dtype('uint16'):
        a = a/65536.0
    elif a.dtype==dtype('uint16'):
        a = a/32767.0
    elif isfloatarray(a):
        pass
    else:
        raise Exception("unknown image type: "+a.dtype)
    if a.ndim==3: 
        a = mean(a,2)
    return a


def write_image_gray(fname,image,normalize=0):
    """Write an image to disk.  If the image is of floating point
    type, its values are clipped to the range [0,1],
    multiplied by 255 and converted to unsigned bytes.  Otherwise,
    the image must be of type unsigned byte."""
    if isfloatarray(image):
        image = array(255*clip(image,0.0,1.0),'B')
    assert image.dtype==dtype('B'),"array has wrong dtype: %s"%image.dtype
    im = array2pil(image)
    im.save(fname)

@checks(str,_=ABINARY2)
def read_image_binary(fname,dtype='i',pageno=0):
    """Read an image from disk and return it as a binary image
    of the given dtype."""
    if type(fname)==tuple: fname,pageno = fname
    assert pageno==0
    pil = PIL.Image.open(fname)
    a = pil2array(pil)
    if a.ndim==3: a = amax(a,axis=2)
    return array(a>0.5*(amin(a)+amax(a)),dtype)

@checks(str,ABINARY2)
def write_image_binary(fname,image):
    """Write a binary image to disk. This verifies first that the given image
    is, in fact, binary.  The image may be of any type, but must consist of only
    two values."""
    assert image.ndim==2
    image = array(255*(image>midrange(image)),'B')
    im = array2pil(image)
    im.save(fname)

@checks(AINT3,_=AINT2)
def rgb2int(a):
    """Converts a rank 3 array with RGB values stored in the
    last axis into a rank 2 array containing 32 bit RGB values."""
    assert a.ndim==3
    assert a.dtype==dtype('B')
    return array(0xffffff&((0x10000*a[:,:,0])|(0x100*a[:,:,1])|a[:,:,2]),'i')

@checks(AINT2,_=AINT3)
def int2rgb(image):
    """Converts a rank 3 array with RGB values stored in the
    last axis into a rank 2 array containing 32 bit RGB values."""
    assert image.ndim==2
    assert isintarray(image)
    a = zeros(list(image.shape)+[3],'B')
    a[:,:,0] = (image>>16)
    a[:,:,1] = (image>>8)
    a[:,:,2] = image
    return a

@checks(LIGHTSEG,_=DARKSEG)
def make_seg_black(image):
    assert isintegerarray(image),"%s: wrong type for segmentation"%image.dtype
    image = image.copy()
    image[image==0xffffff] = 0
    return image

@checks(DARKSEG,_=LIGHTSEG)
def make_seg_white(image):
    assert isintegerarray(image),"%s: wrong type for segmentation"%image.dtype
    image = image.copy()
    image[image==0] = 0xffffff
    return image

@checks(str,_=LINESEG)
def read_line_segmentation(fname):
    """Reads a line segmentation, that is an RGB image whose values
    encode the segmentation of a text line.  Returns an int array."""
    pil = PIL.Image.open(fname)
    a = pil2array(pil)
    assert a.dtype==dtype('B')
    assert a.ndim==3
    image = rgb2int(a)
    result = make_seg_black(image)
    return result

@checks(str,LINESEG)
def write_line_segmentation(fname,image):
    """Writes a line segmentation, that is an RGB image whose values
    encode the segmentation of a text line."""
    a = int2rgb(make_seg_white(image))
    im = array2pil(a)
    im.save(fname)

@checks(str,_=PAGESEG)
def read_page_segmentation(fname):
    """Reads a page segmentation, that is an RGB image whose values
    encode the segmentation of a page.  Returns an int array."""
    pil = PIL.Image.open(fname)
    a = pil2array(pil)
    assert a.dtype==dtype('B')
    assert a.ndim==3
    segmentation = rgb2int(a)
    segmentation = make_seg_black(segmentation)
    return segmentation

@checks(str,PAGESEG)
def write_page_segmentation(fname,image):
    """Writes a page segmentation, that is an RGB image whose values
    encode the segmentation of a page."""
    assert image.ndim==2
    assert image.dtype in [dtype('int32'),dtype('int64')]
    a = int2rgb(make_seg_white(image))
    im = array2pil(a)
    im.save(fname)

def iulib_page_iterator(files):
    for fname in files:
        image = read_image_gray(fname)
        yield image,fname

class RegionExtractor:
    """A class facilitating iterating over the parts of a segmentation."""
    def __init__(self):
        self.cache = {}
    def clear(self):
        del self.cache
        self.cache = {}
    def setImage(self,image):
        return self.setImageMasked(image)
    def setImageMasked(self,image,mask=None,lo=None,hi=None):
        """Set the image to be iterated over.  This should be an RGB image,
        ndim==3, dtype=='B'.  This picks a subset of the segmentation to iterate
        over, using a mask and lo and hi values.."""
        assert image.dtype==dtype('B') or image.dtype==dtype('i'),"image must be type B or i"
        if image.ndim==3: image = rgb2int(image)
        assert image.ndim==2,"wrong number of dimensions"
        self.image = image
        labels = image
        if lo is not None: labels[labels<lo] = 0
        if hi is not None: labels[labels>hi] = 0
        if mask is not None: labels = bitwise_and(labels,mask)
        labels,correspondence = morph.renumber_labels_ordered(labels,correspondence=1)
        self.labels = labels
        self.correspondence = correspondence
        self.objects = [None]+morph.find_objects(labels)
    def setPageColumns(self,image):
        """Set the image to be iterated over.  This should be an RGB image,
        ndim==3, dtype=='B'.  This iterates over the columns."""
        self.setImageMasked(image,0xff0000,hi=0x800000)
    def setPageParagraphs(self,image):
        """Set the image to be iterated over.  This should be an RGB image,
        ndim==3, dtype=='B'.  This iterates over the paragraphs (if present
        in the segmentation)."""
        self.setImageMasked(image,0xffff00,hi=0x800000)
    def setPageLines(self,image):
        """Set the image to be iterated over.  This should be an RGB image,
        ndim==3, dtype=='B'.  This iterates over the lines."""
        self.setImageMasked(image,0xffffff,hi=0x800000)
    def id(self,i):
        """Return the RGB pixel value for this segment."""
        return self.correspondence[i]
    def x0(self,i):
        """Return x0 (column) for the start of the box."""
        return self.comp.x0(i)
    def x1(self,i):
        """Return x0 (column) for the end of the box."""
        return self.comp.x1(i)
    def y0(self,i):
        """Return y0 (row) for the start of the box."""
        return h-self.comp.y1(i)-1
    def y1(self,i):
        """Return y0 (row) for the end of the box."""
        return h-self.comp.y0(i)-1
    def bbox(self,i):
        """Return the bounding box in raster coordinates
        (row0,col0,row1,col1)."""
        r = self.objects[i]
        #print "@@@bbox",i,r
        return (r[0].start,r[1].start,r[0].stop,r[1].stop)
    def bboxMath(self,i):
        """Return the bounding box in math coordinates
        (row0,col0,row1,col1)."""
        h = self.image.shape[0]
        (y0,x0,y1,x1) = self.bbox(i)
        return (h-y1-1,x0,h-y0-1,x1)
    def length(self):
        """Return the number of components."""
        return len(self.objects)
    def mask(self,index,margin=0):
        """Return the mask for component index."""
        b = self.objects[index]
        #print "@@@mask",index,b
        m = self.labels[b]
        m[m!=index] = 0
        if margin>0: m = improc.pad_by(m,margin)
        return array(m!=0,'B')
    def extract(self,image,index,margin=0):
        """Return the subimage for component index."""
        h,w = image.shape[:2]
        (r0,c0,r1,c1) = self.bbox(index)
        mask = self.mask(index,margin=margin)
        return image[max(0,r0-margin):min(h,r1+margin),max(0,c0-margin):min(w,c1+margin),...]
    def extractMasked(self,image,index,grow=0,bg=None,margin=0,dtype=None):
        """Return the masked subimage for component index, elsewhere the bg value."""
        if bg is None: bg = amax(image)
        h,w = image.shape[:2]
        mask = self.mask(index,margin=margin)
        # FIXME ... not circular
        if grow>0: mask = morphology.binary_dilation(mask,iterations=grow) 
        mh,mw = mask.shape
        box = self.bbox(index)
        r0,c0,r1,c1 = box
        subimage = improc.cut(image,(r0,c0,r0+mh-2*margin,c0+mw-2*margin),margin,bg=bg)
        return where(mask,subimage,bg)

    

################################################################
### Simple record object.
################################################################

class Record:
    """A simple record datatype that allows initialization with
    keyword arguments, as in Record(x=3,y=9)"""
    def __init__(self,**kw):
        self.__dict__.update(kw)
    def like(self,obj):
        self.__dict__.update(obj.__dict__)
        return self

################################################################
### Histograms
################################################################

def chist(l):
    """Simple counting histogram.  Takes a list of items
    and returns a list of (count,object) tuples."""
    counts = {}
    for c in l:
        counts[c] = counts.get(c,0)+1
    hist = [(v,k) for k,v in counts.items()]
    return sorted(hist,reverse=1)

################################################################
### multiprocessing
################################################################

def number_of_processors():
    """Estimates the number of processors."""
    return multiprocessing.cpu_count()
    # return int(os.popen("cat /proc/cpuinfo  | grep 'processor.*:' | wc -l").read())

def parallel_map(fun,jobs,parallel=0,chunksize=1):
    if parallel<2:
        for e in jobs:
            result = fun(e)
            yield result
    else:
        try:
            pool = multiprocessing.Pool(parallel)
            for e in pool.imap_unordered(fun,jobs,chunksize):
                yield e
        finally:
            pool.close()
            pool.join()
            del pool

################################################################
### exceptions
################################################################

class Unimplemented():
    "Exception raised when a feature is unimplemented."
    def __init__(self,s):
        Exception.__init__(self,inspect.stack()[1][3])

class BadClassLabel(Exception):
    "Exception for bad class labels in a dataset or input."
    def __init__(self,s):
        Exception.__init__(self,s)

class RecognitionError(Exception):
    "Some kind of error during recognition."
    def __init__(self,explanation,**kw):
        self.context = kw
        s = [explanation]
        s += ["%s=%s"%(k,summary(kw[k])) for k in kw]
        message = " ".join(s)
        Exception.__init__(self,message)

def check_valid_class_label(s):
    """Determines whether the given character is a valid class label.
    Control characters and spaces are not permitted."""
    if type(s)==unicode:
        if re.search(r'[\0-\x20]',s):
            raise BadClassLabel(s)
    elif type(s)==str:
        if re.search(r'[^\x21-\x7e]',s):
            raise BadClassLabel(s)
    else:
        raise BadClassLabel(s)

def summary(x):
    """Summarize a datatype as a string (for display and debugging)."""
    if type(x)==numpy.ndarray:
        return "<ndarray %s %s>"%(x.shape,x.dtype)
    if type(x)==str and len(x)>10:
        return '"%s..."'%x
    if type(x)==list and len(x)>10:
        return '%s...'%x
    return str(x)

################################################################
### file name manipulation
################################################################

from default import getlocal

@checks(str,_=str)
def findfile(name,error=1):
    """Find some OCRopus-related resource by looking in a bunch off standard places.
    (FIXME: The implementation is pretty adhoc for now.
    This needs to be integrated better with setup.py and the build system.)"""
    local = getlocal()
    path = name
    if os.path.exists(path) and os.path.isfile(path): return path
    path = local+name
    if os.path.exists(path) and os.path.isfile(path): return path
    path = local+"/gui/"+name
    if os.path.exists(path) and os.path.isfile(path): return path
    path = local+"/models/"+name
    if os.path.exists(path) and os.path.isfile(path): return path
    path = local+"/words/"+name
    if os.path.exists(path) and os.path.isfile(path): return path
    _,tail = os.path.split(name)
    path = tail
    if os.path.exists(path) and os.path.isfile(path): return path
    path = local+tail
    if os.path.exists(path) and os.path.isfile(path): return path
    if error:
        raise IOError("file '"+path+"' not found in . or /usr/local/share/ocropus/")
    else:
        return None

@checks(str)
def finddir(name):
    """Find some OCRopus-related resource by looking in a bunch off standard places.
    (This needs to be integrated better with setup.py and the build system.)"""
    local = getlocal()
    path = name
    if os.path.exists(path) and os.path.isdir(path): return path
    path = local+name
    if os.path.exists(path) and os.path.isdir(path): return path
    _,tail = os.path.split(name)
    path = tail
    if os.path.exists(path) and os.path.isdir(path): return path
    path = local+tail
    if os.path.exists(path) and os.path.isdir(path): return path
    raise IOError("file '"+path+"' not found in . or /usr/local/share/ocropus/")

@checks(str)
def allsplitext(path):
    """Split all the pathname extensions, so that "a/b.c.d" -> "a/b", ".c.d" """
    match = re.search(r'((.*/)*[^.]*)([^/]*)',path)
    if not match:
        return path,""
    else:
        return match.group(1),match.group(3)

@checks(str)
def base(path):
    return allsplitext(path)[0]

@checks(str,{str,unicode})
def write_text(file,s):
    """Write the given string s to the output file."""
    with open(file,"w") as stream:
        if type(s)==unicode: s = s.encode("utf-8")
        stream.write(s)

@checks([str])
def glob_all(args):
    """Given a list of command line arguments, expand all of them with glob."""
    result = []
    for arg in args:
        expanded = sorted(glob.glob(arg))
        if len(expanded)<1:
            raise Exception("%s: expansion did not yield any files"%arg)
        result += expanded
    return result

@checks([str])
def expand_args(args):
    """Given a list of command line arguments, if the
    length is one, assume it's a book directory and expands it.
    Otherwise returns the arguments unchanged."""
    if len(args)==1 and os.path.isdir(args[0]):
        return sorted(glob.glob(args[0]+"/????/??????.png"))
    else:
        return args

class OcropusFileNotFound:
    """Some file-not-found error during OCROpus processing."""
    def __init__(self,fname):
        self.fname = fname
    def __str__(self):
        return "<OcropusFileNotFound "+self.fname+">"

data_paths = [
    ".",
    "./models",
    "./data",
    "./gui",
    "/usr/local/share/ocropus/models",
    "/usr/local/share/ocropus/data",
    "/usr/local/share/ocropus/gui",
    "/usr/local/share/ocropus",
]

def ocropus_find_file(fname):
    """Search for OCRopus-related files in common OCRopus install
    directories (as well as the current directory)."""
    if os.path.exists(fname):
        return fname
    for path in data_paths:
        full = path+"/"+fname
        if os.path.exists(full): return full
    raise OcropusFileNotFound(fname)

def fexists(fname):
    """Returns fname if it exists, otherwise None."""
    if os.path.exists(fname): return fname
    return None

def fvariant(fname,kind,gt=""):
    """Find the file variant corresponding to the given file name.
    Possible fil variants are line (or png), rseg, cseg, fst, costs, and txt.
    Ground truth files have an extra suffix (usually something like "gt",
    as in 010001.gt.txt or 010001.rseg.gt.png).  By default, the variant
    with the same ground truth suffix is produced.  The non-ground-truth
    version can be produced with gt="", the ground truth version can
    be produced with gt="gt" (or some other desired suffix)."""
    if gt!="": gt = "."+gt
    base,ext = allsplitext(fname)
    # text output
    if kind=="txt":
        return base+gt+".txt"
    assert gt=="","gt suffix may only be supplied for .txt files (%s,%s,%s)"%(fname,kind,gt)
    # a text line image
    if kind=="line" or kind=="png" or kind=="bin":
        return base+".bin.png"
    if kind=="nrm":
        return base+".nrm.png"
    # a recognition lattice
    if kind=="lattice":
        return base+gt+".lattice"
    # raw segmentation
    if kind=="rseg":
        return base+".rseg.png"
    # character segmentation
    if kind=="cseg":
        return base+".cseg.png"
    # text specifically aligned with cseg (this may be different from gt or txt)
    if kind=="aligned":
        return base+".aligned"
    # per character costs
    if kind=="costs":
        return base+".costs"
    raise Exception("unknown kind: %s"%kind)

def fcleanup(fname,gt,kinds):
    """Removes all the variants of the file given by gt
    and the list of kinds."""
    for kind in kinds:
        s = fvariant(fname,kind,gt)
        if os.path.exists(s): os.unlink(s)

def ffind(fname,kind,gt=None):
    """Like fvariant, but throws an IOError if the file variant
    doesn't exist."""
    s = fvariant(fname,kind,gt=gt)
    if not os.path.exists(s):
        raise IOError(s)
    return s

def fopen(fname,kind,gt=None,mode="r"):
    """Like fvariant, but opens the file."""
    return open(fvariant(fname,kind,gt),mode)

################################################################
### Utility for setting "parameters" on an object: a list of keywords for
### changing instance variables.
################################################################

def set_params(object,kw,warn=1):
    """Given an object and a dictionary of keyword arguments,
    set only those object properties that are already instance
    variables of the given object.  Returns a new dictionary
    without the key,value pairs that have been used.  If
    all keywords have been used, afterwards, len(kw)==0."""
    kw = kw.copy()
    for k,v in kw.items():
        if hasattr(object,k):
            setattr(object,k,v)
            del kw[k]
    return kw

################################################################
### warning and logging
################################################################

def caller():
    """Just returns info about the caller in string for (for error messages)."""
    frame = sys._getframe(2)
    info = inspect.getframeinfo(frame)
    result = "%s:%d (%s)"%(info.filename,info.lineno,info.function)
    del frame
    return result

def logging(message,*args):
    """Write a log message (to stderr by default)."""
    message = message%args
    sys.stderr.write(message)

def die(message,*args):
    """Die with an error message."""
    message = message%args
    message = caller()+" FATAL "+message+"\n"
    sys.stderr.write(message)
    sys.exit(1)

def warn(message,*args):
    """Give a warning message."""
    message = message%args
    message = caller()+" WARNING "+message+"\n"
    sys.stderr.write(message)

already_warned = {}

def warn_once(message,*args):
    """Give a warning message, but just once."""
    c = caller()
    if c in already_warned: return
    already_warned[c] = 1
    message = message%args
    message = c+" WARNING "+message+"\n"
    sys.stderr.write(message)

def quick_check_page_components(page_bin,dpi):
    """Quickly check whether the components of page_bin are
    reasonable.  Returns a value between 0 and 1; <0.5 means that
    there is probably something wrong."""
    return 1.0

def quick_check_line_components(line_bin,dpi):
    """Quickly check whether the components of line_bin are
    reasonable.  Returns a value between 0 and 1; <0.5 means that
    there is probably something wrong."""
    return 1.0

def deprecated(func):
    """This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emmitted
    when the function is used."""
    def newFunc(*args, **kwargs):
        warnings.warn("Call to deprecated function %s." % func.__name__,
                      category=DeprecationWarning,stacklevel=2)
        return func(*args, **kwargs)
    newFunc.__name__ = func.__name__
    newFunc.__doc__ = func.__doc__
    newFunc.__dict__.update(func.__dict__)
    return newFunc

################################################################
### conversion functions
################################################################

def ustrg2unicode(u,lig=ligatures.lig):
    """Convert an iulib ustrg to a Python unicode string; the
    C++ version iulib.ustrg2unicode does weird things for special
    symbols like -3"""
    result = ""
    for i in range(u.length()):
        value = u.at(i)
        if value>=0:
            c = lig.chr(value)
            if c is not None:
                result += c
            else:
                result += "<%d>"%value
    return result

### code for instantiation native components

def pyconstruct(s):
    """Constructs a Python object from a constructor, an expression
    of the form x.y.z.name(args).  This ensures that x.y.z is imported.
    In the future, more forms of syntax may be accepted."""
    env = {}
    if "(" not in s:
        s += "()"
    path = s[:s.find("(")]
    if "." in path:
        module = path[:path.rfind(".")]
        print "import",module
        exec "import "+module in env
    return eval(s,env)

def mkpython(name):
    """Tries to instantiate a Python class.  Gives an error if it looks
    like a Python class but can't be instantiated.  Returns None if it
    doesn't look like a Python class."""
    if name is None or len(name)==0:
        return None
    elif type(name) is not str:
        return name()
    elif name[0]=="=":
        return pyconstruct(name[1:])
    elif "(" in name or "." in name:
        return pyconstruct(name)
    else:
        return None

def make_ICleanupGray(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create CleanupGray component for '%s'"%name
    assert "cleanup_gray" in dir(result)
    return result
def make_ICleanupBinary(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create CleanupBinary component for '%s'"%name
    assert "cleanup_binary" in dir(result)
    return result
def make_IBinarize(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create Binarize component for '%s'"%name
    assert "binarize" in dir(result)
    return result
def make_ITextImageClassification(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create TextImageClassification component for '%s'"%name
    assert "textImageProbabilities" in dir(result)
    return result
def make_ISegmentPage(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create SegmentPage component for '%s'"%name
    assert "segment" in dir(result)
    return result
def make_ISegmentLine(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create SegmentLine component for '%s'"%name
    assert "charseg" in dir(result)
    return result
def make_IGrouper(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create Grouper component for '%s'"%name
    assert "setSegmentation" in dir(result)
    assert "getLattice" in dir(result)
    return result
def make_IRecognizeLine(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create RecognizeLine component for '%s'"%name
    assert "recognizeLine" in dir(result)
    return result
def make_IModel(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create Model component for '%s'"%name
    assert "outputs" in dir(result)
    return result
def make_IExtractor(name):
    """Make a native component or a Python component.  Anything containing
    a "(" is assumed to be a Python component."""
    result = mkpython(name)
    assert result is not None,"cannot create Extractor component for: '%s'"%name
    assert "extract" in dir(name)
    return result

################################################################
### alignment, segmentations, and conversions
################################################################

def intarray_as_unicode(a,skip0=1):
    """Given an integer array containing unicode codepoints,
    returns a unicode string with those codepoints."""
    result = u""
    for i in range(len(a)):
        if a[i]!=0:
            assert a[i]>=0 and a[i]<0x110000,"%d (0x%x) character out of range"%(a[i],a[i])
            result += unichr(a[i])
    return result
    
def rect_union(rectangles):
    """Given a list of lists or tuples, where each list/tuple
    represents a rectangle (x0,y0,x1,y1), returns the
    union of all the rectangles."""
    if len(rectangles)<1: return (0,0,-1,-1)
    r = array(rectangles)
    return (amin(r[:,0]),amax(r[:,0]),amin(r[:,1]),amax(r[:1]))

################################################################
### loading and saving components
################################################################

# This code has to deal with a lot of special cases for all the
# different formats we have accrued.

def obinfo(ob):
    """A bit of information about the given object.  Returns
    the str representation of the object, and if it has a shape,
    also includes the shape."""
    result = str(ob)
    if hasattr(ob,"shape"): 
        result += " "
        result += str(ob.shape)
    return result

def save_component(file,object,verbose=0,verify=0):
    """Save an object to disk in an appropriate format.  If the object
    is a wrapper for a native component (=inherits from
    CommonComponent and has a comp attribute, or is in package
    ocropus), write it using ocropus.save_component in native format.
    Otherwise, write it using Python's pickle.  We could use pickle
    for everything (since the native components pickle), but that
    would be slower and more confusing."""
    if hasattr(object,"save_component"):
        object.save_component(file)
        return
    if object.__class__.__name__=="CommonComponent" and hasattr(object,"comp"):
        # FIXME -- get rid of this eventually
        import ocropus
        ocropus.save_component(file,object.comp)
        return
    if type(object).__module__=="ocropus":
        import ocropus
        ocropus.save_component(file,object)
        return
    if verbose: 
        print "[save_component]"
    if verbose:
        for k,v in object.__dict__.items():
            print ":",k,obinfo(v)
    with open(file,"wb") as stream:
        pickle.dump(object,stream,pickle_mode)
    if verify:
        if verbose: 
            print "[trying to read it again]"
        with open(file,"rb") as stream:
            test = pickle.load(stream)

def load_component(file):
    """Load a component from disk.  If file starts with "@", it is
    taken as a Python expression and evaluated, but this can be overridden
    by starting file with "=".  Otherwise, the contents of the file are
    examined.  If it looks like a native component, it is loaded as a line
    recognizers if it can be identified as such, otherwise it is loaded
    with load_Imodel as a model.  Anything else is loaded with Python's
    pickle.load."""

    if file[0]=="=":
        return pyconstruct(file[1:])
    elif file[0]=="@":
        file = file[1:]
    with open(file,"r") as stream:
        # FIXME -- get rid of this eventually
        start = stream.read(128)
    if start.startswith("<object>\nlinerec\n"):
        # FIXME -- get rid of this eventually
        warnings.warn("loading old-style linerec: %s"%file)
        result = RecognizeLine()
        import ocropus
        result.comp = ocropus.load_IRecognizeLine(file)
        return result
    if start.startswith("<object>"):
        # FIXME -- get rid of this eventually
        warnings.warn("loading old-style cmodel: %s"%file)
        import ocroold
        result = ocroold.Model()
        import ocropus
        result.comp = ocropus.load_IModel(file)
        return result
    with open(file,"rb") as stream:
        return pickle.load(stream)

def load_linerec_OBSOLETE(file,wrapper=None):
    """Loads a line recognizer.  If the argument is
    a character recognizer, wraps the wrapper around
    it (default: CmodelLineRecognizer)."""
    component = load_component(file)
    if hasattr(component,"recognizeLine"):
        return component
    if hasattr(component,"coutputs"):
        return wrapper(cmodel=component)
    raise Exception("wanted linerec, got %s"%component)

def binarize_range(image,dtype='B',threshold=0.5):
    """Binarize an image by its range."""
    threshold = (amax(image)+amin(image))*threshold
    scale = 1
    if dtype=='B': scale = 255
    return array(scale*(image>threshold),dtype=dtype)

def simple_classify(model,inputs):
    """Given a model, classify the inputs with the model."""
    result = []

def gtk_yield():
    import gtk
    while gtk.events_pending():
       gtk.main_iteration(False)

def draw_pseg(pseg,axis=None):
    if axis is None:
        axis = subplot(111)
    h = pseg.dim(1)
    regions = ocropy.RegionExtractor()
    regions.setPageLines(pseg)
    for i in range(1,regions.length()):
        x0,y0,x1,y1 = (regions.x0(i),regions.y0(i),regions.x1(i),regions.y1(i))
        p = patches.Rectangle((x0,h-y1-1),x1-x0,y1-y0,edgecolor="red",fill=0)
        axis.add_patch(p)

def draw_aligned(result,axis=None):
    raise Error("FIXME draw_aligned")
    if axis is None:
        axis = subplot(111)
    axis.imshow(NI(result.image),cmap=cm.gray)
    cseg = result.cseg
    if type(cseg)==numpy.ndarray: cseg = common.lseg2narray(cseg)
    ocropy.make_line_segmentation_black(cseg)
    ocropy.renumber_labels(cseg,1)
    bboxes = ocropy.rectarray()
    ocropy.bounding_boxes(bboxes,cseg)
    s = re.sub(r'\s+','',result.output)
    h = cseg.dim(1)
    for i in range(1,bboxes.length()):
        r = bboxes.at(i)
        x0,y0,x1,y1 = (r.x0,r.y0,r.x1,r.y1)
        p = patches.Rectangle((x0,h-y1-1),x1-x0,y1-y0,edgecolor=(0.0,0.0,1.0,0.5),fill=0)
        axis.add_patch(p)
        if i>0 and i-1<len(s):
            axis.text(x0,h-y0-1,s[i-1],color="red",weight="bold",fontsize=14)
    draw()

from matplotlib import patches
import pylab

def draw_rect(p0,p1,w0,w1,**kw):
    p = patches.Rectangle((p0,p1),w0,w1,**kw)  # edgecolor="red",fill=0
    pylab.gca().add_patch(p)

def draw_slrect(b,**kw):
    draw_rect(b[1].start,b[0].start,b[1].stop-b[1].start,b[0].stop-b[0].start,**kw)

def plotgrid(data,d=10,shape=(30,30)):
    """Plot a list of images on a grid."""
    ion()
    gray()
    clf()
    for i in range(min(d*d,len(data))):
        subplot(d,d,i+1)
        row = data[i]
        if shape is not None: row = row.reshape(shape)
        imshow(row)
    ginput(1,timeout=0.1)

def showrgb(r,g=None,b=None):
    if g is None: g = r
    if b is None: b = r
    imshow(array([r,g,b]).transpose([1,2,0]))

def showgrid(l,cols=None,n=400,titles=None,xlabels=None,ylabels=None,**kw):
    import pylab
    if "cmap" not in kw: kw["cmap"] = pylab.cm.gray
    if "interpolation" not in kw: kw["interpolation"] = "nearest"
    n = minimum(n,len(l))
    if cols is None: cols = int(sqrt(n))
    rows = (n+cols-1)//cols
    for i in range(n):
        pylab.xticks([]); pylab.yticks([])
        pylab.subplot(rows,cols,i+1)
        pylab.imshow(l[i],**kw)
        if titles is not None: pylab.title(str(titles[i]))
        if xlabels is not None: pylab.xlabel(str(xlabels[i]))
        if ylabels is not None: pylab.ylabel(str(ylabels[i]))

def gt_explode(s):
    l = re.split(r'_(.{1,4})_',s)
    result = []
    for i,e in enumerate(l):
        if i%2==0:
            result += [c for c in e]
        else:
            result += [e]
    result = [re.sub("\001","_",s) for s in result]
    result = [re.sub("\002","\\\\",s) for s in result]
    return result

def gt_implode(l):
    result = []
    for c in l:
        if c=="_":
            result.append("___")
        elif len(c)<=1:
            result.append(c)
        elif len(c)<=4:
            result.append("_"+c+"_")
        else:
            raise Exception("cannot create ground truth transcription for: %s"%l)
    return "".join(result)

@checks(int,sequence=int,frac=int,_=BOOL)
def testset(index,sequence=0,frac=10):
    # this doesn't have to be good, just a fast, somewhat random function
    return sequence==int(abs(sin(index))*1.23456789e6)%frac

def midrange(image,frac=0.5):
    """Computes the center of the range of image values
    (for quick thresholding)."""
    return frac*(amin(image)+amax(image))
