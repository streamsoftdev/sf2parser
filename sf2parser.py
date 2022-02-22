#Copyright 2022 Nathan Harwood
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.

import struct
import os
import numpy as np
import sys


# based on https://freepats.zenvoid.org/sf2/sfspec24.pdf


class SF2Parser():
    def __init__(self,filename:str,
                    ignore_errors:bool = False,
                    ignoreIndexOutOfRange:bool = True):
        self.fp = open(filename,mode='rb')
        self.ignore_errors=ignore_errors
        self.ignoreIndexOutOfRange=ignoreIndexOutOfRange
        self.buffer=bytearray([])

    def check(self,length):
        x = len(self.buffer) - length
        if x<0:
            self.buffer+=(self.fp.read(-x))

    def SHORT(self)->int:
        self.check(2)
        short, = struct.unpack('<h',self.buffer[:2])
        self.buffer=self.buffer[2:]
        return short

    def WORD(self)->int:
        self.check(2)
        word, = struct.unpack('<H',self.buffer[:2])
        self.buffer=self.buffer[2:]
        return word

    def DWORD(self)->int:
        self.check(4)
        dword, = struct.unpack('<L',self.buffer[:4])
        self.buffer = self.buffer[4:]
        return dword

    def FOURCC(self)->str:
        self.check(4)
        code = self.buffer[0:4].decode()
        self.buffer = self.buffer[4:]
        return code

    def BYTE(self)->int:
        self.check(1)
        byte, = struct.unpack('B',self.buffer[:1])
        self.buffer = self.buffer[1:]
        return byte

    def CHAR(self)->int:
        self.check(1)
        char, = struct.unpack('b',self.buffer[:1])
        self.buffer = self.buffer[1:]
        return char

    def ZSTR(self,length)->str:
        self.check(length)
        zstr_len = 0
        while self.buffer[zstr_len]!=0 and zstr_len<length:
            zstr_len+=1
        fault=False
        if zstr_len==length or zstr_len==0:
            fault=True
        zstr = self.buffer[:zstr_len].decode()
        self.buffer = self.buffer[length:]
        return zstr,fault

    def chunk_header(self):
        ckID = self.FOURCC()
        ckSize = self.DWORD()
        return ckID, ckSize

    def skip(self,length):
        self.fp.read(length)    

    def parse_phdr(self,ckSize):
        """ Lists all presets within the SoundFont compatible file. 
        
        `wPreset` is the MIDI Preset Number. `wBank` is the MIDI Bank Number. 
        If two headers have the same `wPreset` and `wBank` then the first occurring
        header is the active preset. The special case of a General MIDI percussion
        bank is handled by a `wBank` value of 128. `wPresetBagNdx` is an index
        to the preset's zone list in the 'pbag' structure. Other attributes
        are reserved for future use (default 0)."""

        if ckSize % 38 != 0:
            raise Exception(f"Chunk 'phdr' size {ckSize} is not a multiple of 38.")
        phdr=[]
        lastPresetBagNdx = None
        while ckSize > 0:
            self.check(38)
            name, _ = self.ZSTR(20)
            sfPresetHeader={
                'achPresetName':name,
                'wPreset':self.WORD(),
                'wBank':self.WORD(),
                'wPresetBagNdx':self.WORD(),
                'dwLibrary':self.DWORD(),
                'dwGenre':self.DWORD(),
                'dwMorphology':self.DWORD()
            }
            if lastPresetBagNdx != None and lastPresetBagNdx > sfPresetHeader['wPresetBagNdx']:
                raise Exception(f"wPresetBagNdx values are not monotonically increasing.")
            lastPresetBagNdx = sfPresetHeader['wPresetBagNdx']
            phdr.append(sfPresetHeader)
            ckSize -= 38
        return phdr

    def parse_pbag(self,ckSize):
        """ Lists all zones within the SoundFont compatiable file. 
        
        The first zone in a given preset is located at that preset's `wPresetBagNdx`.
        `wGenNdx` is an index to the preset's zone list of generators in the 'pgen'
        structure. `wModNdx` is an index to its list of modulators in the 'pmod'
        structure. """

        if ckSize % 4 != 0:
            raise Exception(f"Chunk 'pbag' size {ckSize} is not a multiple of 4.")
        pbag=[]
        lastGenNdx=None
        lastModNdx=None
        while ckSize > 0:
            self.check(4)
            sfPresetBag = {
                'wGenNdx':self.WORD(),
                'wModNdx':self.WORD()
            }
            if lastGenNdx != None and lastGenNdx > sfPresetBag['wGenNdx']:
                raise Exception(f"wGenNdx values are not monotonically increasing.")
            lastGenNdx = sfPresetBag['wGenNdx']
            if lastModNdx != None and lastModNdx > sfPresetBag['wModNdx']:
                raise Exception(f"wModNdx values are not monotonically increasing.")
            lastGenNdx = sfPresetBag['wModNdx']
            pbag.append(sfPresetBag)
            ckSize -= 4
        return pbag

    def SFModulator(self):
        return self.WORD()

    def SFGenerator(self):
        return self.WORD()

    def SFTransform(self):
        return self.WORD()

    def parse_pmod(self,ckSize):
        """ Lists all preset zone modulators within the SoundFont compatible file.
        
        The preset zone's `wModNdx` points to the first modulator for that preset zone.
        `modAmount` is a signed value indicating the degree to which the source
        modulates the destination. A zero value indicates there is no fixed amount. """

        if ckSize % 10 != 0:
            raise Exception(f"Chunk 'pmod' size {ckSize} is not a multiple of 10.")
        pmod=[]
        while ckSize>0:
            self.check(10)
            sfModList = {
                'sfModSrcOper':self.SFModulator(),
                'sfModDestOper':self.SFGenerator(),
                'modAmount':self.SHORT(),
                'sfModAmtSrcOper':self.SFModulator(),
                'sfModTransOper':self.SFTransform()
            }
            pmod.append(sfModList)
            ckSize-=10
        return pmod

    def genAmountType(self):
        return self.WORD()

    def parse_pgen(self,ckSize):
        """ Lists preset zone generators for each preset zone within the SoundFont
        compatible file.
        
        The preset zone's `wGenNdx` points to the first generator for that preset zone.
        Unless the zone is a global zone, the last generator in the list is an 'Instrument'
        generator, whose value is a pointer to the instrument associated with that zone.
        If a 'key range' generator exists for the preset zone, it is always the first
        generator in the list for that preset zone. If a 'velocity range' generator
        exists for the preset zone, it will only be preceeded by a key range generator.
        Any generators following an instrument generator will be ignored.

        If two generators in the same zone have the same `sfGenOper` enumeration, the
        first one will be ignored.
        """

        if ckSize % 4 != 0:
            raise Exception(f"Chunk 'pgen' size {ckSize} is not a multiple of 4.")
        pgen=[]
        while ckSize>0:
            self.check(4)
            sfGenList = {
                'sfGenOper':self.SFGenerator(),
                'genAmount':self.genAmountType()
            }
            pgen.append(sfGenList)
            ckSize-=4
        return pgen

    def parse_inst(self,ckSize):
        """ Lists all instruments within the SoundFont compatible file. 
        
        `wInstBagNdx` is an index to the instrument's zone list in the 'ibag' structure. """
        if ckSize % 22 != 0:
            raise Exception(f"Chunk 'inst' size {ckSize} is not a multiple of 22.")
        inst=[]
        lastInstBagNdx=None
        while ckSize>0:
            self.check(22)
            name,_ = self.ZSTR(20)
            sfInst = {
                'achInstName':name,
                'wInstBagNdx':self.WORD()
            }
            if lastInstBagNdx!=None and lastInstBagNdx > sfInst['wInstBagNdx']:
                raise Exception(f"wInstBagNdx values are not monontically increasing.")
            lastInstBagNdx = sfInst['wInstBagNdx']
            inst.append(sfInst)
            ckSize-=22
        return inst

    def parse_ibag(self,ckSize):
        """ Lists all instrument zones within the SoundFont compatiable file. 
        
        The first zone in a given instrument is located at that instrument's `wInstBagNdx`.
        """  

        if ckSize % 4 != 0:
            raise Exception(f"Chunk 'ibag' size {ckSize} is not a multiple of 4.")
        ibag=[]
        lastInstGenNdx=None
        lastInstModNdx=None
        while ckSize>0:  
            self.check(4)    
            sfInstBag = {
                'wInstGenNdx':self.WORD(),
                'wInstModNdx':self.WORD()
            }
            if lastInstGenNdx != None and lastInstGenNdx > sfInstBag['wInstGenNdx']:
                raise Exception(f"wInstGenNdx values are not monotonically increasing.")
            lastInstGenNdx = sfInstBag['wInstGenNdx']
            if lastInstModNdx != None and lastInstModNdx > sfInstBag['wInstModNdx']:
                raise Exception(f"wInstModNdx values are not monotonically increasing.")
            lastInstModNdx = sfInstBag['wInstModNdx']
            ibag.append(sfInstBag)
            ckSize-=4
        return ibag

    def parse_imod(self,ckSize):
        """ Lists all instrument zone modulators within the SoundFont compatible file.
        
        The zone's `wInstModNdx` points to the first modulator for that zone.
        `modAmount` is a signed value indicating the degree to which the source
        modulates the destination. A zero value indicates there is no fixed amount. """

        if ckSize % 10 != 0:
            raise Exception(f"Chunk 'imod' size {ckSize} is not a multiple of 10.")
        imod=[]
        while ckSize>0:
            self.check(10)
            sfModList = {
                'sfModSrcOper':self.SFModulator(),
                'sfModDestOper':self.SFGenerator(),
                'modAmount':self.SHORT(),
                'sfModAmtSrcOper':self.SFModulator(),
                'sfModTransOper':self.SFTransform()
            }
            imod.append(sfModList)
            ckSize-=10
        return imod

    def parse_igen(self,ckSize):
        """ Lists zone generators for each instrument zone within the SoundFont
        compatible file.
        
        The zone's `wInstGenNdx` points to the first generator for that zone.
        Unless the zone is a global zone, the last generator in the list is an 'sampleID'
        generator, whose value is a pointer to the sample associated with that zone.
        If a 'key range' generator exists for the zone, it is always the first
        generator in the list for that zone. If a 'velocity range' generator
        exists for the zone, it will only be preceeded by a key range generator.
        Any generators following a sampleID generator will be ignored.

        If two generators in the same zone have the same `sfGenOper` enumeration, the
        first one will be ignored.
        """

        if ckSize % 4 != 0:
            raise Exception(f"Chunk 'pigen' size {ckSize} is not a multiple of 4.")
        igen=[]
        while ckSize>0:
            self.check(4)
            sfInstGenList = {
                'sfGenOper':self.SFGenerator(),
                'genAmount':self.genAmountType()
            }
            igen.append(sfInstGenList)
            ckSize-=4
        return igen

    def SFSampleLink(self):
        return self.WORD()

    def parse_shdr(self,ckSize):
        """ Lists all samples within the 'smpl' structure and any referenced ROM
        samples.
        
        """

        if ckSize % 46 != 0:
            raise Exception(f"Chunk 'shdr' size {ckSize} is not a multiple of 46.")
        shdr=[]
        while ckSize>0:
            self.check(46)
            name,_=self.ZSTR(20)
            sfSample = {
                'achSampleName':name,
                'dwStart':self.DWORD(),
                'dwEnd':self.DWORD(),
                'dwStartloop':self.DWORD(),
                'dwEndloop':self.DWORD(),
                'dwSampleRate':self.DWORD(),
                'byOriginalPitch':self.BYTE(),
                'chPitchCorrection':self.CHAR(),
                'wSampleLink':self.WORD(),
                'sfSampleType':self.SFSampleLink()
            }
            shdr.append(sfSample)
            ckSize-=46
        return shdr

    def parse_pdta(self):
        """ Parse the Preset, Instrument, and Sample Header data """

        pdta={
            'phdr':None,
            'pbag':None,
            'pmod':None,
            'pgen':None,
            'inst':None,
            'ibag':None,
            'imod':None,
            'igen':None,
            'shdr':None
        }
        ckID, ckSize = self.chunk_header()
        if ckID=='LIST':
            formID = self.FOURCC()
            if formID != "pdta":
                raise Exception(f"Expected form 'pdta' but found '{formID}'.")
            ckSize -= 4
            while ckSize > 0:
                subCkID,subCkSize = self.chunk_header()
                if subCkID in pdta:
                    class_method = getattr(SF2Parser,f"parse_{subCkID}")
                    pdta[subCkID]= class_method(self,subCkSize)
                else:
                    raise Exception(f"Unknown chunk '{subCkID}' of size '{ckSize}'")
                ckSize -= subCkSize+8
            if ckSize<0:
                raise Exception(f"Exceeded the chunk length for 'pdta' with expected length {ckSize}.")
        else:
            raise Exception(f"Expected chunk 'pdta' but found chunk '{ckID}' of size '{ckSize}'")
        
        if 'phdr' in pdta and 'pbag' in pdta:
            if pdta['phdr'][-2]['wPresetBagNdx']>=len(pdta['phdr']):
                msg=f"The wPresetBagNdx {pdta['phdr'][-2]['wPresetBagNdx']} is outside the number of zones {len(pdta['phdr'])}."
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
        else:
            raise Exception(f"Missing either or both of 'phdr' and 'pbag' chunks.")
        
        if 'pbag' in pdta and 'pmod' in pdta and 'pgen' in pdta:
            if pdta['pbag'][-2]['wGenNdx']>=len(pdta['pgen']):
                msg=f"The wGenNdx {pdta['pbag'][-2]['wGenNdx']} is outside the number of generators {len(pdta['pgen'])}."
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
            if pdta['pbag'][-2]['wModNdx']>=len(pdta['pmod']):
                msg=f"The wModNdx {pdta['pbag'][-2]['wModNdx']} is outside the number of modulators {len(pdta['pmod'])}."
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
        else:
            raise Exception(f"Missing either or both of 'pmod' and 'pgen' chunks.")
        if 'inst' in pdta and 'ibag' in pdta:
            if pdta['inst'][-2]['wInstBagNdx']>=len(pdta['ibag']):
                msg=f"The wInstBagNdx {pdta['inst'][-2]['wInstBagNdx']} is outside the number of instrument zones {len(pdta['ibag'])}"
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
        else:
            raise Exception(f"Missing either or both of 'inst' and 'ibag' chunks.")
        if 'ibag' in pdta and 'imod' in pdta and 'igen' in pdta:
            if pdta['ibag'][-2]['wInstGenNdx']>=len(pdta['igen']):
                msg=f"The wInstGenNdx {pdta['ibag'][-2]['wInstGenNdx']} is outside the number of instrument generators {len(pdta['igen'])}."
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
            if pdta['ibag'][-2]['wInstModNdx']>=len(pdta['imod']):
                msg=f"The wInstModNdx {pdta['ibag'][-2]['wInstModNdx']} is outside the number of instrument modulators {len(pdta['imod'])}."
                if not self.ignoreIndexOutOfRange:
                    raise Exception(msg)
                else:
                    print(msg)
        else:
            raise Exception(f"Missing either or both of 'imod' and 'igen' chunks.")
        return pdta

    

    def parse_smpl(self,ckSize):
        """ Parse the high order (16 bit signed) sample data. 
        
        Data is returned as 24 bit signed values (coarse samples). """

        self.check(ckSize)
        dtype = np.dtype(np.int16)
        dtype = dtype.newbyteorder('<')
        sample_data = np.frombuffer(self.buffer[0:ckSize],dtype=dtype)
        sample_data*=2**8 # 24-bit coarse samples
        self.buffer = self.buffer[ckSize:]
        return sample_data

    def parse_sm24(self,ckSize):
        """ Parse the low order (8 bit unsigned) sample data. """

        self.check(ckSize)
        dtype = np.dtype(np.int8)
        sample_data = np.frombuffer(self.buffer[0:ckSize],dtype=dtype)
        self.buffer = self.buffer[ckSize:]
        return sample_data

    def parse_sdta(self):
        """ Parse the Sample Binary Data """

        sdta={
            'smpl':None,
            'sm24':None,
        }
        ckID, ckSize = self.chunk_header()
        if ckID=='LIST':
            formID = self.FOURCC()
            if formID != "sdta":
                raise Exception(f"Expected form 'sdta' but found '{formID}'.")
            ckSize -= 4
            while ckSize > 0:
                subCkID,subCkSize = self.chunk_header()
                if subCkID == 'smpl':
                    sdta['smpl']=self.parse_smpl(subCkSize)
                elif subCkID == 'sm24':
                    sdta['isng']=self.parse_isng(subCkSize)
                ckSize -= subCkSize + 8
        else:
            raise Exception(f"Expected chunk 'sdta' but found chunk '{ckID}' of size '{ckSize}'")
        if type(sdta['smpl']) != type(None) and\
            type(sdta['sm24']) != type(None):
            sdta['smpl']=np.bitwise_or(sdta['smpl'],sdta['sm24'])
            sdta.pop('sm24') # reduce memory requirements
        return sdta

    def parse_ifil(self,ckSize):
        """ sf Version Tag, e.g. 2.01.
        
        `wMajor` is the value to the left of the decimal point and
        `wMinor` is the value to the right of the decimal point.
        These values can be used by applications which read SoundFont
        compatible files to determine if the format of the file is
        usable by the program. """

        if ckSize != 4 and not self.ignore_errors:
            raise Exception(f"Chunk 'ifil' has illegal size {ckSize}.")
        return {
            'wMajor':self.WORD(),
            'wMinor':self.WORD()
        }
    
    def parse_isng(self,ckSize):
        """ Wavetable sound engine for which the file was optimized, e.g. 'EMU8000'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szSoundEngine':"EMU8000" if fault else zstr,
            'szSoundEngine_raw':zstr
        }
       

    def parse_INAM(self,ckSize):
        """ The name of the SoundFont compatible bank, e.g. 'General Midi'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szName':None if fault else zstr,
            'szName_raw':zstr
        }

    def parse_irom(self,ckSize):
        """ Identifies a particular wavetable sound data ROM to which any ROM
        samples refer. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szROM':None if fault else zstr,
            'szROM_raw':zstr
        }

    def parse_iver(self,ckSize):
        """ Identifies the wavetable sound data ROM revision to which any ROM
        samples refer.

        `wMajor` is the value to the left of the decimal point and
        `wMinor` is the value to the right of the decimal point.
        Is used by drivers to verify that the ROM data referenced by the file
        is located in the exact locations specified by the sound headers. """

        if ckSize != 4 and not self.ignore_errors:
            raise Exception(f"Chunk 'iver' has illegal size {ckSize}.")
        return {
            'wMajor':self.WORD(),
            'wMinor':self.WORD()
        }

    def parse_ICRD(self,ckSize):
        """ The creation date fo the SoundFont compatible bank,
         e.g. 'July 15, 1997'. """
        
        zstr,fault = self.ZSTR(ckSize)
        return {
            'szDate':None if fault else zstr,
            'szDate_raw':zstr
        }
       
    def parse_IENG(self,ckSize):
        """ The names of any sound designers or engineers responsible for
        the SoundFont compatible bank, e.g. 'Jonh Q. Sounddesigner'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szName':None if fault else zstr,
            'szName_raw':zstr
        }
        

    def parse_IPRD(self,ckSize):
        """ The specific product for which this SoundFont compatible bank
        is intended, e.g. 'SBAWE64 Gold'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szProduct':None if fault else zstr,
            'szProduct_raw':zstr
        }
       

    def parse_ICOP(self,ckSize):
        """ The copyright assertion string associated with the SoundFont
        compatible bank, e.g. 'Copyright (c) 1997 E-mu Systems, Inc.'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szCopyright':None if fault else zstr,
            'szCopyright_raw':zstr
        }
       

    def parse_ICMT(self,ckSize):
        """ Any comments associated with the SoundFont compatible bank,
         e.g. 'This is a comment'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szComment':None if fault else zstr,
            'szcommen_raw':zstr
        }
        

    def parse_ISFT(self,ckSize):
        """ The SoundFont compatible tools used to create and most recently
        modify the SoundFont compatible bank, 
        e.g. 'Preditor 2.00a: Vienna SF Studio 2.0:'. """

        zstr,fault = self.ZSTR(ckSize)
        return {
            'szTools':None if fault else zstr,
            'szTools_raw':zstr
        }
        

    def parse_INFO(self):
        """ Supplemental Information """

        INFO={
            'ifil':None,
            'isng':None,
            'INAM':None,
            'irom':[],
            'iver':[],
            'ICRD':[],
            'IENG':[],
            'IPRD':[],
            'ICOP':[],
            'ICMT':[],
            'ISFT':[]
        }
        ckID,ckSize = self.chunk_header()
        if ckID == "LIST":
            formID = self.FOURCC()
            if formID != "INFO":
                raise Exception(f"Expected form 'INFO' but found '{formID}'.")
            ckSize -= 4
            while ckSize > 0:
                subCkID,subCkSize = self.chunk_header()
                if subCkID in INFO:
                    class_method = getattr(SF2Parser,f"parse_{subCkID}")
                    if INFO[subCkID] == None:
                        INFO[subCkID]=class_method(self,subCkSize)
                    else:
                        INFO[subCkID].append(class_method(self,subCkSize))
                else:
                    raise Exception(f"Unexpected chunk '{subCkID}' of size {subCkSize}.")
                ckSize -= subCkSize+8
        else:
           raise Exception(f"Expected chunk 'LIST' but found chunk '{ckID}' of size {ckSize}")
        if INFO['ifil']==None and not self.ignore_errors:
            raise Exception("Missing chunk 'ifil'.")
        return INFO

    def parse_sfbk(self):
        """ Parse the SoundFont compatible file. """

        #ckID, ckSize = self.chunk_header()
        formID = self.FOURCC()
        if formID=='sfbk':
            self.INFO = self.parse_INFO()
            self.sdta = self.parse_sdta()
            self.pdta = self.parse_pdta()
        else:
            print(f"Found form header '{formID}' - probably not a SF2 file.")
            

    def parse(self):
        """ The main entry point for parsing the file. """

        self.INFO={}
        self.sdta={}
        self.pdta={}
        ckID, ckSize = self.chunk_header()
        if ckID=='RIFF':
            self.parse_sfbk()
        else:
            print(f"Found chunk '{ckID}' of size {ckSize} - probably not a SF2 file.")
            self.skip(ckSize)

    def get_sfVersionTag(self):
        return f"{self.INFO['ifil']['wMajor']}.{self.INFO['ifil']['wMinor']}"

    def get_szSoundEngine(self):
        return self.INFO['isng']['szSoundEngine']

    def get_szName(self):
        return self.INFO['INAM']['szName']

    def get_engName(self):
        if len(self.INFO['IENG'])>0:
            zstr=self.INFO['IENG'][0]['szName']
            for x in self.INFO['IENG'][1:]:
                zstr+=". "+x['szName']
            return zstr
        else:
            return ""
        
    def get_copyright(self):
        if len(self.INFO['ICOP'])>0:
            zstr=self.INFO['ICOP'][0]['szCopyright']
            for x in self.INFO['ICOP'][1:]:
                zstr+=". "+x['szCopyright']
            return zstr
        else:
            return ""

    def get_comment(self):
        if len(self.INFO['ICMT'])>0:
            zstr=self.INFO['ICMT'][0]['szComment']
            for x in self.INFO['ICMT'][1:]:
                zstr+=". "+x['szComment']
            return zstr
        else:
            return ""

    def get_tools(self):
        if len(self.INFO['ISFT'])>0:
            zstr=self.INFO['ISFT'][0]['szTools']
            for x in self.INFO['ISFT'][1:]:
                zstr+=". "+x['szTools']
            return zstr
        else:
            return ""
    
    def get_date(self):
        if len(self.INFO['ICRD'])>0:
            zstr=self.INFO['ICRD'][0]['szDate']
            for x in self.INFO['ICRD'][1:]:
                zstr+=". "+x['szDate']
            return zstr
        else:
            return ""

    def print_summary(self):
        print(f"SoundFont Version {self.get_sfVersionTag()}")
        print(f"'{self.get_szName()}', {self.get_engName()}, for the {self.get_szSoundEngine()} sound engine.")
        print(f"Copyrights: {self.get_copyright()}")
        print(f"Comments: {self.get_comment()}")
        print(f"Dates: {self.get_date()}")
        print(f"Number of samples: {len(self.pdta['shdr'])}")

    def list_samples(self):
        for sample in self.pdta['shdr'][0:-1]:
            print(f"'{sample['achSampleName']}' {sample['dwSampleRate']}Hz {sample['dwEnd']-sample['dwStart']} samples")
    
if __name__ == "__main__":
    sf2parser = SF2Parser(sys.argv[1])
    sf2parser.parse()
    sf2parser.print_summary()
    sf2parser.list_samples()