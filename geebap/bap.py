#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Main module holding the Bap Class and its methods """

from __future__ import print_function
import ee

# Initialize EE
import ee.data
if not ee.data._initialized: ee.Initialize()

import satcol
import season as temp
import functions
import datetime
import date
import scores
import masks
import filters
import time
import sys
from collections import namedtuple
from geetools import tools
import json
import pprint

pp = pprint.PrettyPrinter(indent=2)

MIN_YEAR = 1970
MAX_YEAR = datetime.date.today().year

def check_type(name, param, type):
    """ Wrapper to check parameter's type """
    if param and not isinstance(param, type):
        raise ValueError(
            "argument '{}' must be {}".format(name, type.__name__))
    else:
        return


class Bap(object):
    debug = False
    verbose = True
    def __init__(self, year=None, range=(0, 0), colgroup=None, scores=None,
                 masks=None, filters=None, season=None, fmap=None,
                 only_sr=False):
        """ Main Class designed to be independet of the site and the method
        that will be used to generate the composite.

        :param year: The year of the final composite. If the season covers two
            years the last one will be used. Ej.

            ..code:: python

                season = Season(ini="15-12", end="15-01")
                bap = Bap(year=2000)

            to generate the composite the code will use images from
            15-12-1999 to 15-01-2000
        :type year: int
        :param range: Range which indicates before and after the `year`
            parameter. For example:

            ..code:: python

                bap = Bap(year=2001, range=(1, 1))
                bap.date_range()

            >> [2000, 2001, 2002]

        :type range: tuple
        :param colgroup: Group of collections. If `None`, it'll use
            `season.SeasonPriotiry`
        :type colgroup: satcol.ColGroup
        :param scores: scores (scores.Score) to use in the process
        :type scores: tuple
        :param masks: masks (masks.Mask) to use in the process
        :type masks: tuple
        :param filters: filters (filters.Filter) to use in the process
        :type filters: tuple
        :param season: growing season
        :type season: season.Season
        :param fmap: This param will change..
        :type fmap: function
        :param only_sr: use only SR collections
        :type only_sr: bool
        """

        check_type("year", year, int)
        check_type("season", season, temp.Season)

        if year < MIN_YEAR or year > MAX_YEAR:
            raise ValueError(
        "The year must be greatre than {} and less than {}".format(
            MIN_YEAR, MAX_YEAR))

        self.only_sr = only_sr
        self.year = year
        self.range = range
        self.scores = scores
        self.masks = masks
        self.filters = filters
        self.season = season
        self.fmap = fmap
        self.colgroup = colgroup

    @property
    def date_to_set(self):
        return ee.Date(
            str(self.year) + "-" + self.season.doy).millis().getInfo()

    @property
    def ini_date(self):
        return self.season.add_year(self.year - self.range[0])[0]

    @property
    def end_date(self):
        return self.season.add_year(self.year + self.range[1])[1]

    @property
    def ini_season(self):
        return self.season.add_year(self.year)[0]

    @property
    def end_season(self):
        return self.season.add_year(self.year)[1]

    @property
    def date_range(self):
        try:
            i = self.year - abs(self.range[0])
            f = self.year + abs(self.range[1]) + 1

            return range(i, f)
        except:
            return None

    @property
    def score_names(self):
        if self.scores:
            punt = [p.name for p in self.scores]
            return functions.replace_duplicate(punt)
        else:
            return []

    @property
    def colgroup(self):
        return self._colgroup

    @colgroup.setter
    def colgroup(self, value):
        if value is None:
            s = set()
            for a in self.date_range:
                s = s.union(
                    set([col for col in temp.SeasonPriority.relation[a]]))


            if self.only_sr:
                colist = [satcol.Collection.from_id(ID) for ID in s if satcol.Collection.from_id(ID).process == 'SR']
            else:
                colist = [satcol.Collection.from_id(ID) for ID in s]

            self._colgroup = satcol.ColGroup(colist)
        else:
            self._colgroup = value

    def collist(self):
        """ List of Collections.
        DEPRECATED: use `self.colgroup.ids`

        If the 'family' of `colgroup` property of the object is not 'Landsat',
        then it'll use the given `colgroup`, else

        :return: list of collections that will be used
        :rtype: list
        """
        fam = self.colgroup.family()
        if self.debug: print("COLLECTIONS family:", fam)

        if fam != "Landsat":
            return self.colgroup.collections
        else:
            # Ids de las collections dadas
            s1 = set([col.ID for col in self.colgroup.collections])

            # Ids de la lista de collections presentes en el range de
            # temporadas
            s2 = set()
            for a in self.date_range:
                s2 = s2.union(
                    set([col for col in temp.SeasonPriority.relation[a]]))

            intersect = s1.intersection(s2)
            if self.debug:
                print("Collections inside ColGroup:", s1)
                print("Prior Collections:", s2)
                print("Intersection:", intersect)
            return [satcol.Collection.from_id(ID) for ID in intersect]

    def collection(self, site, indices=None, normalize=True, bbox=0,
                   force=True):
        """ Apply masks, filters and scores to the given collection group and
        return one image collecion with all images and their score bands.

        :param indices: vegetation indices to include in the final image. If
            None, no index is calculated
        :type indices: tuple
        :param site: Site geometry
        :type site: ee.Geometry
        :param normalize: Whether to normalize the final score from 0 to 1
            or not
        :type normalize: bool
        :return: a namedtuple:

            - col: the collection with filters, masks and scores applied
            - dictprop: dict that will go to the metadata of the Image
        """
        ################# DEBUG #########################################
        # Get site centroid for debugging purpose
        geom = site if isinstance(site, ee.Geometry) else site.geometry()
        centroid = geom.centroid()

        # Function to get the value of the first image of the collection in
        # its centroid
        def get_col_val(col):
            ''' Values of the first image in the centroid '''

            values = tools.get_values(col, centroid, 30, 'client')
            pp.pprint(values)
        #################################################################

        # NamedTuple for the OUTPUT
        output = namedtuple("ColBap", ("col", "dictprop"))

        # If there is no fmap, an empty function is made
        if self.fmap is None:
            fmap = lambda x: x
        else:
            fmap = self.fmap

        # colfinal = ee.ImageCollection()
        colfinal = ee.List([])

        # Get site's region
        try:
            region = site.geometry().bounds().getInfo()['coordinates'][0]
        except AttributeError:
            region = site.getInfo()['coordinates'][0]
        except:
            raise AttributeError

        # score's names (to sum all at the end)
        scores = self.score_names

        # max score that it can get
        maxpunt = reduce(
            lambda i, punt: i+punt.max, self.scores, 0) if self.scores else 1

        # dict to include in the Metadata
        toMetadata = dict()

        # list of collections
        collist = self.colgroup.collections

        if self.verbose:
            print("scores:", scores)
            # print("satellites:", [c.ID for c in collist])
            print("satellites:", self.colgroup.ids)

        for colobj in collist:

            # Collection ID
            cid = colobj.ID

            # short name of the collection to add to Metadata
            short = colobj.short

            # col_id
            bid = colobj.bandIDimg

            # Add col_id to metadata.
            # col_id_11 = 'L8TAO'
            # etc..
            toMetadata["col_id_"+str(colobj.col_id)] = short

            # EE Collection
            c = colobj.colEE

            # Filtro por el site
            if isinstance(site, ee.Feature): site = site.geometry()
            c2 = c.filterBounds(site)

            # Renombra las bandas aca?
            # c2 = c2.map(col.rename())

            if self.verbose: print("\nSatellite:", colobj.ID)
            if self.debug:
                pp.pprint(colobj.kws)
                print("SIZE AFTER FILTER SITE:")
                print(c2.size().getInfo())

            # Iterate over the years. There will be more than 1 year if
            # param `range` is not (0, 0)

            for year in self.date_range:
                # Create a new Collection object
                col = satcol.Collection.from_id(cid)

                ini = self.season.add_year(year)[0]
                end = self.season.add_year(year)[1]

                if self.verbose: print("ini:", ini, ",end:", end)

                # Filter Date
                c = c2.filterDate(ini, end)

                ## FILTROS ESTABAN ACA

                # If after filter the collection there is no image, continue
                size = c.size().getInfo()
                if self.verbose: print("size after filters:", size)
                if size == 0: continue  # 1

                if self.debug:
                    print("INITIAL CENTROID VALUES")
                    print(get_col_val(c))

                # apply a boundry box over the region
                if bbox == 0:
                    def cut(img):
                        return img.clip(site)
                else:
                    def cut(img):
                        bounds = site.buffer(bbox)
                        return img.clip(bounds)

                c = c.map(cut)

                if self.debug:
                    print("AFTER CLIPPING WITH REGION")
                    print(get_col_val(c))

                # Before appling the cloud mask, if collection is Landsat 7
                # with slc-off, then convert the mask to zero so the gap
                # does not affect cloud dist score and maskpercent score

                slcoff = False

                if short == 'L7USGS' or short == 'L7TOA':
                    if year in temp.SeasonPriority.l7_slc_off:
                        # Convert masked values to zero
                        c = c.map(tools.mask2zero)
                        slcoff = True

                if self.debug:
                    print('AFTER MASK 2 ZERO')
                    print(get_col_val(c))

                # MASKS
                if self.masks:
                    for m in self.masks:
                        c = c.map(
                            m.map(col=col, year=year, colEE=c))
                        if self.debug:
                            print("AFTER THE MASK ")
                            print(m.nombre)
                            print(get_col_val(c))

                # Convert masked values to zero
                # c = c.map(tools.mask2zero)

                # Rename the bands to match all collections
                c = c.map(col.rename(drop=True))

                # Cambio las bandas en comun de las collections
                bandasrel = []

                if self.debug:
                    print("AFTER RENAMING BANDS:")
                    print(get_col_val(c))

                # Scale from 0 to 1
                c = c.map(col.do_scale())

                if self.debug:
                    if c.size().getInfo() > 0:
                        print("AFTER SCALING:")
                        print(get_col_val(c))

                # Indixes
                if indices:
                    for i in indices:
                        f = col.INDICES[i]
                        c = c.map(f)
                        if self.debug:
                            print("SIZE AFTER COMPUTE "+i)
                            print(c.size().getInfo())

                # Before appling scores, apply fmap
                c = c.map(fmap)

                # Apply scores
                if self.scores:
                    for p in self.scores:
                        if self.verbose: print("** "+p.name+" **")
                        # Espero el tiempo seteado en cada puntaje
                        sleep = p.sleep
                        for t in range(sleep):
                            sys.stdout.write(str(t+1)+".")
                            if (t+1) == sleep: sys.stdout.write('\n')
                            time.sleep(1)

                        if slcoff and p.name == "score-maskper":
                            c = c.map(p.map(col=col, year=year, colEE=c, geom=site, include_zero=False))
                        else:
                            c = c.map(p.map(col=col, year=year, colEE=c, geom=site))

                        # DEBUG
                        if self.debug: # and n > 0:
                            print("value:")
                            print(get_col_val(c))

                # Filtros
                if self.filters:
                    for filter in self.filters:
                        c = filter.apply(c, col=col, anio=self.year)

                # METODO NUEVO: selecciono las bandas en comun desp de unir
                # todas las collections usando un metodo distinto

                if self.debug:
                    if c.size().getInfo() > 0:
                        print("AFTER SELECTING COMMON BANDS:")
                        print(get_col_val(c))

                # Convert masked values to zero
                c = c.map(tools.mask2zero)

                # Add date band
                c = c.map(date.Date.map())

                # Add col_id band
                def addBandID(img):
                    return img.addBands(bid)
                c = c.map(addBandID)

                if self.debug:
                    print("AFTER ADDING col_id BAND:")
                    print(get_col_val(c))

                # Convierto a lista para agregar a la coleccion anterior
                c_list = c.toList(2500)
                colfinal = colfinal.cat(c_list)

                # Agrego col id y year al diccionario para propiedades
                n_imgs = "n_imgs_{cid}_{a}".format(cid=short, a=year)
                toMetadata[n_imgs] = functions.get_size(c)

        # comprueba que la lista final tenga al menos un elemento
        # s_fin = colfinal.size().getInfo()  # 2
        s_fin = functions.get_size(colfinal)

        # DEBUG
        if self.verbose: print("final collection size:", s_fin)

        if s_fin > 0:
            newcol = ee.ImageCollection(colfinal)

            # Selecciono las bandas en comun de todas las imagenes
            newcol = functions.select_match(newcol)

            if self.debug:
                print("BEFORE score:")
                print(scores)
                print(get_col_val(c))

            # Calcula el puntaje total sumando los puntajes
            ftotal = tools.sumBands("score", scores)
            newcol = newcol.map(ftotal)

            if self.debug:
                print("AFTER score:")
                print(get_col_val(c))

            if normalize:
                newcol = newcol.map(
                    tools.parametrize((0, maxpunt), (0, 1), ("score",)))

            if self.debug:
                print("AFTER parametrize:")
                print(get_col_val(c))

            return output(newcol, toMetadata)
        elif force:
            bands_from_col = self.colgroup.bandsrel()
            bands_from_scores = self.score_names if self.score_names else ['score']
            bands_from_indices = list(indices) if indices else []
            bands = bands_from_col + bands_from_scores + bands_from_indices

            img = ee.Image.constant(0).select([0], [bands[0]])

            for i, band in enumerate(bands):
                if i == 0: continue
                newimg = ee.Image.constant(0).select([0], [band])
                img = img.addBands(newimg)

            return output(ee.ImageCollection([img]), toMetadata)
        else:
            return output(None, toMetadata)

    @staticmethod
    def calcUnpix_generic(col, score):
        """ DO NOT USE. It's a test method """
        imgCol = col
        # tamcol = funciones.execli(imgCol.size().getInfo)()

        img = imgCol.qualityMosaic(score)

        if Bap.debug:
            print(" AFTER qualityMosaic:", img.bandNames().getInfo())

        # CONVIERTO LOS VALORES ENMASCARADOS EN 0
        # img = tools.mask2zero(img)
        img = tools.mask2zero(img)

        return img

    def calcUnpix(self, site, name="score", bands=None, **kwargs):
        """ Generate the BAP composite using the pixels that have higher
        final score. This version uses GEE function 'qualiatyMosaic"

        :param site: Site geometry
        :type site: ee.Geometry
        :param name: name of the band that has the final score
        :type name: str
        :param bands: name of the bands to include in the final image
        :type bands: list
        :param kwargs:
        :return: A namedtuple:
            .image = the Best Available Pixel Composite (ee.Image)
            .col = the collection of images used to generate the BAP
                (ee.ImageCollection)
        :rtype: namedtuple
        """
        colbap = self.collection(site=site, **kwargs)

        col = colbap.col
        prop = colbap.dictprop

        img = Bap.calcUnpix_generic(col, name)

        img = img if bands is None else img.select(*bands)

        fechaprop = {"system:time_start": self.date_to_set}
        prop.update(fechaprop)
        return img.set(prop)

    def bestpixel(self, site, name="score", bands=None,
                  indices=None, normalize=True, bbox=0, force=True):
        """ Generate the BAP composite using the pixels that have higher
        final score. This is a custom method

        :param site: Site geometry
        :type site: ee.Geometry
        :param name: name of the band that has the final score
        :type name: str
        :param bands: name of the bands to include in the final image
        :type bands: list
        :param kwargs: see Bap.collection() method
        :return: A namedtuple:
            .image = the Best Available Pixel Composite (ee.Image)
            .col = the collection of images used to generate the BAP
                (ee.ImageCollection)
        :rtype: namedtuple
        """
        colbap = self.collection(site=site, indices=indices,
                                 normalize=normalize, bbox=bbox, force=force)

        imgCol = colbap.col
        prop = colbap.dictprop

        output = namedtuple("bestpixel", ("image", "col"))

        # SI HAY ALGUNA IMAGEN
        if imgCol is not None:
            img0 = ee.Image(0)

            # ALTERNATIVA PARA OBTENER LA LISTA DE BANDAS
            first = ee.Image(imgCol.first())

            # 'in best pixel 1', first.select('date').getInfo()['bands'])

            listbands = first.bandNames()
            # nbands = tools.execli(listbands.size().getInfo)()
            nbands = tools.execli(listbands.size().getInfo)()

            thelist = []

            # CREO LA IMAGEN INICIAL img0 CON LAS BANDAS NECESARIAS EN 0
            for r in range(0, nbands):
                img0 = ee.Image(0).addBands(img0)
                thelist.append(r)

            img0 = img0.select(thelist, listbands)

            def final(img, maxx):
                maxx = ee.Image(maxx)
                ptotal0 = maxx.select(name)
                ptotal0 = ptotal0.mask().where(1, ptotal0)

                ptotal1 = img.select(name)
                ptotal1 = ptotal1.mask().where(1, ptotal1)

                masc0 = ptotal0.gt(ptotal1)
                masc1 = masc0.Not()

                maxx = maxx.updateMask(masc0)
                maxx = maxx.mask().where(1, maxx)

                img = img.updateMask(masc1)
                img = img.mask().where(1, img)

                maxx = maxx.add(img)

                return ee.Image(maxx)

            img = ee.Image(imgCol.iterate(final, img0))

            # print 'in best pixel 2', img.select('date').getInfo()['bands']

            # SETEO LAS PROPIEDADES
            dateprop = {"system:time_start": self.date_to_set}
            # img = img.set(dateprop)
            prop.update(dateprop)

            # Elimino las barras invertidas
            prop = {k.replace("/","_"):v for k, v in prop.iteritems()}

            img = img if bands is None else img.select(*bands)

            return output(self.setprop(img, **prop), imgCol)
        else:
            if self.verbose:
                print("The process can not be done because the Collections "
                      "have no images. Returns None")
            return output(None, None)

    def setprop(self, img, **kwargs):
        """ Sets properties to the composite.

        - ini_date: Initial date.
        - end_date: End date.

        The images included to generate the BAP are between `ini_data` and
        `end_date`

        :param img: Image to set attributes
        :type img: ee.Image
        :param kwargs: extra parameters passed to the function will be added
            to the image as a property
        :return: the passed image with added properties
        :rtype: ee.Image
        """
        d = {"ini_date": date.Date.local(self.ini_date),
             "end_date": date.Date.local(self.end_date),
             }

        # Agrega los argumentos como propiedades
        d.update(kwargs)

        return img.set(d)

    @classmethod
    def White(cls, year, range, season):
        """ Pre-built subclass using same parameters as White (original
        author of the BAP method) """
        psat = scores.Satellite()
        pdist = scores.CloudDist()
        pdoy = scores.Doy(season=season)
        pop = scores.AtmosOpacity()
        colG = satcol.ColGroup.SR()
        masc = masks.Clouds()
        filt = filters.CloudsPercent()

        pjes = (psat, pdist, pdoy, pop)
        mascs = (masc,)
        filts = (filt,)

        return cls(year, range, scores=pjes, masks=mascs, filters=filts,
                   colgroup=colG, season=season)

    @classmethod
    def Modis(cls, year, range, season, index=None):
        """
        :param index: Vegetation index to use in the scrore computing. It must
            match the one used in the method used to generate the BAP (example:
            bestpixel). If it's None, the index score is not computed.
        :return:
        """
        # Puntajes
        pdist = scores.CloudDist()
        pdoy = scores.Doy(season=season)
        pmasc = scores.MaskPercent()
        pout = scores.Outliers(("nirXred",))

        colG = satcol.ColGroup.Modis()
        masc = masks.Clouds()
        filt = filters.MaskPercent(0.3)

        pjes = [pdist, pdoy, pmasc, pout]

        if index:
            pindice = scores.PIndice(index)
            pout2 = scores.Outliers((index,))
            pjes.append(pindice)
            pjes.append(pout2)

        mascs = (masc,)
        filts = (filt,)

        nirxred = functions.nirXred()

        return cls(year, range, colgroup=colG, season=season,
                   masks=mascs, scores=pjes, fmap=nirxred, filters=filts)
