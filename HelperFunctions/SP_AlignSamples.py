'''

this script takes feat, bound and segsection information and rotates them to minimise 
the error between slices

'''
import numpy as np
import cv2
from scipy.optimize import minimize
from glob import glob
import multiprocessing
from multiprocessing import Pool
from copy import deepcopy
from itertools import repeat
from PIL import Image
if __name__ != "HelperFunctions.SP_AlignSamples":
    from Utilities import *
    from SP_SampleAnnotator import featChangePoint
else:
    from HelperFunctions.Utilities import *
    from HelperFunctions.SP_SampleAnnotator import featChangePoint

# object which contains the reference and target positions between a single matching pair
class sampleFeatures:
    def __init__(self, ref = None, tar = None, fit = None, shape = None):
        self.ref = ref
        self.tar = tar
        self.fit = fit

def align(data, size = 0, cpuNo = False, saving = True, prefix = "tif", refName = None, errorThreshold = 100):

    # This function will take the extracted sample tif file at the set resolution and 
    # translate and rotate them to minimise the error between slices
    # co-ordinates of the key features on that image for alignment
    # Inputs:   (data), directories of the tif files of interest
    #           (featDir), directory of the features
    #           (refImg), sample name of the reference image to be used
    # Outputs:  (), extracts the tissue sample from the slide and aligns them by 
    #           their identified featues

    # get the file of the features information 
    src = data + str(size)
    dataSegmented = src + '/masked/'     
    alignedSamples = src + '/alignedSamples/'
    segInfo = src + '/info/'

    # get the sample slices of the specimen to be processed
    samples = sorted(glob(dataSegmented + "*." + prefix))

    aligner(samples, segInfo, dataSegmented, alignedSamples, saving, refName, cpuNo, errorThreshold)

def aligner(samples, featureInfoPath, srcImgPath, destImgPath, saving = True, refName = None, cpuNo = False, errorThreshold = 100):

    # this function takes all the directories and info and then does the full 
    # rigid alignment and saves where directed:
    # Inputs:   (samples), the paths of all the images to be processed
    #           (segInfo), directory of the features positions found and where to save the 
    #               rigid transformations
    #           (destImgPath), directory to save the aligned samples
    #           (dataSegmented), directory of the images to be processed
    #           (saving), boolean whether to save the full resolution info
    #           (refImg), optional whether to normalise the colours of the images
    #           (cpuNo), number of cores to parallelise processes on

    # use a reference sample to normalise colours
    if refName is not None:
        try: 
            imgDir = glob(srcImgPath + "*" + refName + "*.png")
            while len(imgDir) != 1:
                print("Perhaps you meant...")
                for i in imgDir:
                    print(nameFromPath(i, 3))
                refName = input("Double check sample name and retype: ")
                imgDir = glob(srcImgPath + "*" + refName + "*.png")

            refImg = cv2.imread(imgDir[0])
            print("Refimg " + nameFromPath(imgDir[0], 3) + " used")
        except: 
            refImg = None
            print("No ref image used")
    else:
        refImg = None

    sampleNames = nameFromPath(samples, 3)

    # find the affine transformation necessary to fit the samples
    # NOTE this has to be sequential because the centre of rotation changes for each image
    # so the angles of rotation dont add up
    shiftFeatures(samples, featureInfoPath, destImgPath, 100)

    # get the field shape required for all specimens to fit
    info = sorted(glob(featureInfoPath + "*feat"))[:len(sampleNames)]
    shapes = []
    for i in info:
        shapes.append(np.array(txtToDict(i, float)[1]['shape'])[:2])

    # get all the translations
    translated = txtToDict(featureInfoPath + "all.translated", float)[0]

    # get the shift of all the info to fit the image on the positive value axis
    shiftMa = np.max(dictToArray(translated), axis = 0)
    shiftMi = np.min(dictToArray(translated), axis = 0)

    # combine the shapes and translations to calculate the net shape from the origin per image
    maxShape = np.insert(np.ceil(np.max(np.array(shapes) + np.flip(shiftMa) - np.flip(shiftMi), axis = 0)), 2, 3).astype(int)

    # apply the affine transformations to all the images and info
    if cpuNo is False:
        # serial transformation
        for sample in samples:
            transformSamples(sample, srcImgPath, maxShape, shiftMa, featureInfoPath, destImgPath, saving, refImg)

    else:
        # parallelise with n cores
        with Pool(processes=cpuNo) as pool:
            pool.starmap(transformSamples, zip(samples, repeat(srcImgPath), repeat(maxShape), repeat(shiftMa), repeat(featureInfoPath), repeat(destImgPath), repeat(saving), repeat(refImg)))

    print('Alignment complete')

def shiftFeatures(featPaths, src, alignedSamples, errorThreshold = 100):

    # Function takes the images and translation information and adjusts the images to be aligned and returns the translation vectors used
    # Inputs:   (featNames), the samples being aligned
    #           (src)
    #           (alignedSamples)
    #           (errorThreshold), the maximum error value which is tolerated before 
    #               removing features
    # Outputs:  (translateAll), the translation information to be applied per image
    #           (rotateNet), the rotation information to be applied per image

    # load the identified features
    featRef = {}
    featTar = {}

    featNames = nameFromPath(featPaths, 3)

    for fr, ft in zip(featNames[:-1], featNames[1:]):
        # load all the features
        featRef[fr] = txtToDict(src + fr + ".reffeat", float)                
        featTar[ft] = txtToDict(src + ft + ".tarfeat", float)

                                            
    # store the affine transformations
    translateAll = {}
    rotateNet = {}

    # initialise the first sample with no transformation
    translateAll[featNames[0]] = np.array([0, 0])
    rotateNet[featNames[0]] = [0, 0, 0]
    featsO = sampleFeatures()
    sampleObj = sampleFeatures()

    # perform transformations on neighbouring slices and build them up as you go
    for rF, tF in zip(featRef, featTar):

        # print("Ref0: " + str(featRef[rF]['feat_0']) + " Tar0: " + str(featTar[tF]['feat_0']))
        
        '''
        # select neighbouring features to process
        featsO = {}     # feats optimum, at this initialisation they are naive but they will progressively converge 
        for tF in featNames[i:i+2]:
            featsO[tF] = feats[tF]
        '''

        # get the features to align
        # create the feature matched object (ie these are the pairs of feature that are to be aligned)
        featsO = sampleFeatures()
        featsO.ref = deepcopy(featRef[rF][0])
        featsO.tar = deepcopy(featTar[tF][0])

        # create the sample object (ie these are the features that are on the same object)
        try:    sampleObj.ref = deepcopy(featRef[tF][0])
        except: sampleObj.ref = deepcopy(featTar[tF][0])    # for final match just use the same features
        sampleObj.tar = deepcopy(featTar[tF][0])
        shapeTar = featTar[tF][1]['shape']
        shapeRef = featRef[rF][1]['shape']

        # if there are no features to match, assume fit is true, otherwise set as the 
        # flag in the dictionary
        if (len(featsO.ref) == 0) or (len(featsO.tar) == 0):
            featsO.fit = True
        
        else:
            featsO.fit = featTar[tF][1]['fit']

        # set the initial attempt positional ranges to remove features in the case of 
        # refitting attempts
        atmpR = 1
        atmp = 0
        lastFt = []
        n = 0
        featsMod = deepcopy(featsO)
        translateSum = np.zeros(2).astype(float)
        
        print("Shifting " + tF + " features")
        # -------- CREATE THE MOST OPTIMISED POSSIBLE FIT OF 
        #       FEATURES POSSIBLE, SAVE THE NEW FEATURES AND THEIR 
        #                       TRANSFORMATIONS --------
        while featsO.fit is False:

            # !! Every time the loop starts here, it is trying to fit a NEW set of features !!

            # featMod, the pair of features being fit
            # featO, the pair of features to be fit BEFORE transformations have begun
            # feattmp, the features that have been modified in a single fitting procedure
            #   temporarily stored until they are assigned

            # declare variables for error checking and iteration counting
            errN = 1e6
            errorC = 1e6
            errCnt = 0  
            errorStore = np.ones(3) * 1e6
            translateSum = np.zeros(2).astype(float)
            featsMod = deepcopy(featsO)
            refit = False
            manualFit = False
            
            # mimimise the error per feature of the currently selected feature
            while True:        

                # !! Every time the loop starts here, it is OPTIMISING the fit of the CURRENT features !!
                
                # use the previous error for the next calculation
                errO = errN
                errorCc = errorC

                # get the translation vector
                translation, feattmp, err = translatePoints(featsMod, bestfeatalign = False)
                
                # keep track of a temporary translation
                translateSum += translation

                # find the optimum rotational adjustment and produce modified feats
                _, feattmp, errN, centre, MxErrPnt = rotatePoints(feattmp, bestfeatalign = False, plot = False)

                # print("     Fit " + str(n) + " Error = " + str(errN))

                # change in errors between iterations, using two errors
                errorC = errO - errN

                # store the last n changes in error
                errorStore = np.insert(errorStore, 0, errN)
                errorStore = np.delete(errorStore, -1)
                
                # sometimes the calcultions get stuck, ossiclating between two errrors
                # of the same magnitude but opposite sign
                if errorC + errorCc == 0:
                    errCnt += 1     # count the number of times these ossiclations occur

                # conditions to finish the fitting proceduce
                #   the error of fitting = 0
                #   a turning point has been detected and error is increasing
                if errN == 0:
                    print("     Fitting successful, err/feat = " + str(int(errN))) 
                    featsMod = feattmp      # this set of feats are the ones to use
                    featsO.fit = True

                # positions have converged 
                elif np.round(np.sum(np.diff(errorStore)), 2) <= 0:
                    # if the final error is below a threshold, it is complete
                    # but use the previously fit features
                    if errO < errorThreshold:
                        print("     " + str(len(featsMod.tar)) + "/" + str(len(featTar[tF][0])) + " w err = " + str(int(errN)))
                        print("     Fitting converged, attempt " + str(atmp))
                        featsO.fit = True
                        break

                    # with the current features, if they are not providing a good match
                    # then modify which features are being used to fit
                    else:
                        # print("     Modifying feat, err/feat = " + str(int(errO)))
                        # denseMatrixViewer([featsMod[rF], featsMod[tF], centre[tF]], True)
                        
                        # there have to be at least 3 points left to enable good fitting practice
                        # if there aren't going to be 3 left do a manual fitting process
                        if len(featsMod.tar) < 3: 
                            manualFit = True

                        # set refit boolean
                        refit = True

                        # remove the features which have the most error
                        for m in MxErrPnt:
                            del featsO.tar[m]
                            del featsO.ref[m]
                        print("     " + str(len(featsMod.tar)) + "/" + str(len(featTar[tF][0])) + "feats left @ err = " + str(int(errN)))
                        atmp += 1
                        break

                # if there are only 3 features remaining for the fitting process
                # then it will require manual fitting
                elif errCnt > 10:
                    refit = True
                    break

                # update the current features being modified 
                featsMod = feattmp
                    
            # -------- MODIFY THE FEATURES TO PERFORM A NEW FITTING PROCEDURE --------

            # if there is no possible combination of features that can fit the samples, 
            # manually annotate new one
            if manualFit:

                print("\n\n!! ---- FITTING PROCEDUCE DID NOT CONVERGE  ---- !!\n\n")
                print("     Refitting, err = " + str(errN))

                # denseMatrixViewer([dictToArray(featsMod.ref), dictToArray(featsMod.tar), centre], True)

                # change the original positions used
                feats = featChangePoint(regionOfPath(src, 2), rF, tF, nopts=8, title = "Select eight features on each image")
                
                # go through all the annotations and see if there have actually been any changes made
                same = True
                for cf in commonFeats:
                    # check if any of the annotations have changed
                    if (feats.refP[cf] != featRef[rF][0][cf]).all() or (feats.tarP[cf] != featTar[tF][0][cf]).all():
                        same = False 
                        break

                # if there have been no changes then break the fitting process and accept
                # the fitting proceduce as final
                if same:
                    break

                # update the master dictionary as these are the new features saved
                featRef[rF][0] = feats.refP
                featTar[tF][0] = feats.tarP

                # updated the featO features for a new fitting procedure based on these new
                # modified features
                featsO.ref = feats.refP
                featsO.tar = feats.tarP
                atmp = 0
            
            # if there are enough feature available but alignment didn't converge to 
            # an error low enough, iterate through
            elif refit: 
                continue

            # if a suitable alignment has been found then progress 
            else:
                break

        # -------- CREATE THE SINGLE TRANSLATION AND ROTATION FILES --------

        # replicate the whole fitting proceduce in a single go to be applied to the 
        # images later on
        featToMatch = sampleFeatures()
        featToMatch.ref = deepcopy(featsMod.tar)       # get the fitted feature (ref)
        featToMatch.tar = deepcopy(sampleObj.tar)        # get the original position of features

        # translation, featToMatch, err = translatePoints(featToMatch, True)

        # apply ONLY the translation transformations to the original features so that the 
        # adjustments are made to the optimised feature positions
        for f in featToMatch.tar:
            # print("Orig: " + str(featsMaster['H653A_09_1'][f]))
            featToMatch.tar[f] -= translateSum
            
        translateAll[tF] = translateSum

        # perform a single rotational fitting procedure
        rotateSum = 0

        # view the final points before rotating VS the optimised points
        # denseMatrixViewer([dictToArray(featToMatch[tF]), dictToArray(featsMod[tF]), centre[tF]], True)

        # continue fitting until convergence with the already fitted results
        while abs(errN) > 1e-8:
            rotationAdjustment, featToMatch, errN, cent, MxErrPnt = rotatePoints(featToMatch, bestfeatalign = False, plot = False, centre = centre)
            rotated = rotationAdjustment
            rotateSum += rotationAdjustment
            # print("Fit: " + str(n) + " FINAL FITTING: " + str(errN))
            n += 1
        
        # pass the rotational degree and the centre of rotations
        rotateNet[tF] = [rotateSum, centre[0], centre[1]]  

        # perform the same transformation to the dictionaries 
        for fr in sampleObj.ref: 
            sampleObj.ref[fr] -= translateSum    
        for ft in sampleObj.tar:
            sampleObj.tar[ft] -= translateSum    

        sampleObj.ref = objectivePolar(rotateSum, centre, False, sampleObj.ref) 
        sampleObj.tar = objectivePolar(rotateSum, centre, False, sampleObj.tar) 

        # denseMatrixViewer([featRef[rF][0], sampleObj.tar, featsMod.ref, featsMod.tar, centre], True)
        # denseMatrixViewer([featsMod.ref, featsMod.tar, centre], True)

        # featsMod.ref

        _, L = uniqueKeys([sampleObj.tar, featsMod.tar])

        # save all the original features but transformed to meet fitting criteria 
        dictToTxt(featRef[rF][0], alignedSamples + rF + ".reffeat", fit = featsO.fit, shape = shapeRef)
        dictToTxt(sampleObj.tar, alignedSamples + tF + ".tarfeat", fit = featsO.fit, shape = shapeTar)

        # reasign the sample features after being translated and rotated
        try:    featRef[tF][0] = sampleObj.ref
        except: print("Finished fitting")

    # save the tif shapes, translation and rotation information
    dictToTxt(translateAll, src + "all.translated")
    dictToTxt(rotateNet, src + "all.rotated")

def transformSamples(samplePath, segSamples, maxShape, shift, segInfo, dest, saving = True, refImg = None):
    # this function takes the affine transformation information and applies it to the samples
    # Inputs:   (sample), sample being processed
    #           (segSamples), directory of the segmented samples
    #           (segInfo), directory of the feature information
    #           (dest), directories to save the aligned samples
    #           (saving), boolean whether to save new info
    # Outputs   (), saves an image of the tissue with the necessary padding to ensure all images are the same size and roughly aligned if saving is True

    # get the name of the sample
    sample = nameFromPath(samplePath, 3)

    # Load the entire image
    field = cv2.imread(samplePath)

    refdir = dest + sample + ".reffeat"
    tardir = dest + sample + ".tarfeat"
    tifShapesdir = segInfo + "all.tifshape"
    jpgShapesdir = segInfo + "all.jpgshape"
    translateNetdir = segInfo + "all.translated"
    rotateNetdir = segInfo + "all.rotated"

    # load the whole specimen info
    translateAll = txtToDict(translateNetdir, float)[0]
    
    '''
    # load the tif shapes
    try:
        tifShapes = txtToDict(tifShapesdir, int)[0]

    # if there are no individualised tif shapes, assume they are all the same size
    except:
        tifShapes = {}
        for t in list(translateAll.keys()):
            tifShapes[t] = field.shape
    try:    
        jpegSize = txtToDict(jpgShapesdir, int)[0][sample]
        tifSize = tifShapes[sample]
        shapeR = np.round((tifSize / jpegSize)[0], 1)
    '''

    rotateNet = txtToDict(rotateNetdir, float)[0]
    specInfo = {}

    try: featR = txtToDict(refdir, float); specInfo['reffeat'] = featR[0]; imgShape = featR[1]['shape'][0]
    except: pass

    try: featT = txtToDict(tardir, float); specInfo['tarfeat'] = featT[0]; imgShape = featT[1]['shape'][0]
    except: pass

    # find the scale of the image change
    shapeR = np.round(field.shape[0] / imgShape, 2)
    
    # get the translations and set 0, 0 to be the position of minimum translation
    translateNet = shift - translateAll[sample]

    # get the anlge and centre of rotation used to align the samples
    w = rotateNet[sample][0]
    centre = rotateNet[sample][1:] * shapeR
    # make destinate directory
    dirMaker(dest)

    # ---------- apply the transformations onto the images and info ----------

    yp, xp = translateNet.astype(int)

    # adjust the points for the shifted tif image with the standardised field
    for sI in specInfo:
        for f in specInfo[sI]:
            specInfo[sI][f] = specInfo[sI][f] * shapeR + shift

    # get the section of the image 
    fx, fy, fc = field.shape

    newField = np.zeros(maxShape).astype(np.uint8)      # empty matrix for ALL the images
    
    newField[xp:(xp+fx), yp:(yp+fy), :] += field

    # apply the rotational transformation to the image
    centreMod = centre + translateNet 

    rot = cv2.getRotationMatrix2D(tuple(centreMod), float(w), 1)
    warped = cv2.warpAffine(newField, rot, (maxShape[1], maxShape[0]))

    # NOTE this is very memory intense so probably should reduce the CPU
    # count so that more of the RAM is being used rather than swap
    # perform a colour nomralisation is a reference image is supplied

    # create a low resolution image which contains the adjust features
    # LOAD IN THE ACTUAL WARPED IMAGE
    plotPoints(dest + sample + '_alignedAnnotatedUpdated.jpg', warped, centreMod, specInfo, si = 10)

    # this takes a while so optional
    if saving:
        if refImg is not None:
            for c in range(warped.shape[2]):
                warped[:, :, c] = hist_match(warped[:, :, c], refImg[:, :, c])

        cv2.imwrite(dest + sample + '.tif', warped)                               # saves the adjusted image at full resolution 
    
    # create a condensed image version
    imgr = cv2.resize(warped, (int(warped.shape[1]/shapeR), int(warped.shape[0]/shapeR)))
    
    # normalise the image ONLY if there is a reference image and the full scale
    # image hasn't already been normalised
    if refImg is not None:
        for c in range(warped.shape[2]):
            imgr[:, :, c] = hist_match(imgr[:, :, c], refImg[:, :, c])   

    cv2.imwrite(dest + sample + '.png', imgr)

    print("Done translation of " + sample)

def translatePoints(feats, bestfeatalign = False):

    # get the shift of each frame
    # Inputs:   (feats), dictionary of each feature
    #           (bestfeatalign), boolean if true then will align all the samples
    #           based off a single point, rather than the mean of all
    # Outputs:  (shiftStore), translation applied
    #           (feats), the features after translation
    #           (err), squred error of the target and reference features
    
    featsMod = deepcopy(feats)
    shiftStore = {}
    ref = feats.ref
    tar = feats.tar

    [tarP, refP], featkeys = uniqueKeys([tar, ref])

    if bestfeatalign:
        refP = {}
        tarP = {}
        refP[featkeys[0]] = ref[featkeys[0]]
        tarP[featkeys[0]] = tar[featkeys[0]]

    # get the shift needed and store
    res = minimize(objectiveCartesian, (0, 0), args=(refP, tarP), method = 'Nelder-Mead', tol = 1e-6)
    shift = res.x
    err = objectiveCartesian(res.x, tarP, refP)

    # modify the target positions
    tarM = {}
    for t in tar.keys():
        tarM[t] = tar[t] - shift

    featsMod.tar = tarM

    return(shift, featsMod, err)

def rotatePoints(feats, tol = 1e-6, bestfeatalign = False, plot = False, centre = None):

    # get the rotations of each frame
    # Inputs:   (feats), dictionary of each feature
    # Outputs:  (rotationStore), affine rotation matrix to rotate the IMAGE --> NOTE 
    #                       rotating the image is NOT the same as the features and this doesn't 
    #                       quite work propertly for some reason...
    #           (featsmod), features after rotation
    
    featsMod = deepcopy(feats)
    ref = feats.ref
    tar = feats.tar

    # get the common features
    [tarP, refP], commonFeat = uniqueKeys([tar, ref])

    # if doing best align, use the first feature as the centre of rotation,
    # otherwise use the mean of all the features
    if centre is None:
        if bestfeatalign:
            centre = tarP[commonFeat[0]]
        else:
            centre = findCentre(tarP)
    
    # get the optimal rotation to minimise errors and store
    res = minimize(objectivePolar, -5.0, args=(centre, True, tarP, refP), method = 'Nelder-Mead', tol = tol) 
    tarM = objectivePolar(res.x, centre, False, tar, refP, plot)   # get the transformed features and re-assign as the ref
    rotationStore = float(res.x)

    ref, tarM = uniqueKeys([ref, tarM])[0]

    # errors per point
    errPnt = np.sum((dictToArray(ref) - dictToArray(tarM))**2, axis = 1)

    # get the feature with the greatest error
    # for every 50 features, remove a feature (ie if there are 199 fts, remove 3
    # if 201 remove 4)
    MxErrPnt = []
    ftPos = np.argsort(-errPnt)[:int(np.floor(len(errPnt)/50+1))]
    for f in ftPos:

        MxErrPnt.append(list(tarM.keys())[f])

    # return the average error per point
    err = np.mean(errPnt)

    # reassign this as the new feature
    featsMod.tar = tarM
    
    if plot: denseMatrixViewer([dictToArray(refN), dictToArray(refP), centre], True)

    return(rotationStore, featsMod, err, centre, MxErrPnt)

def plotPoints(dir, imgO, cen, points, si = 50):

    # plot circles on annotated points
    # Inputs:   (dir), either a directory (in which case load the image) or the numpy array of the image
    #           (imgO), image directory
    #           (cen), rotational centre
    #           (points), dictionary or array of points which refer to the co-ordinates on the image
    # Outputs:  (), saves downsampled jpg image with the points annotated

    # load the image
    if type(imgO) is str:
            imgO = cv2.imread(imgO)

    img = imgO.copy()
    colours = [(0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 255)]
    sizes = [1, 0.8, 0.6, 0.4]

    # for each set of points add to the image
    for n, pf in enumerate(points):

        point = points[pf]

        if type(point) is dict:
            point = dictToArray(point)

        for p in point:       # use the target keys in case there are features not common to the previous original 
            pos = tuple(np.round(p).astype(int))
            img = cv2.circle(img, pos, int(si * sizes[n]), tuple(colours[n]), int(si * sizes[n]/2)) 
        
    # plot of the rotation as well using opposite colours
    cen = cen.astype(int)
    # img = cv2.circle(img, tuple(findCentre(points)), si, (0, 255, 0), si) 
    img = cv2.circle(img, tuple(cen), int(si * sizes[n] * 0.8), (255, 0, 0), int(si * sizes[n] * 0.8/2)) 

    # resize the image
    x, y, c = img.shape
    imgResize = cv2.resize(img, (2000, int(2000 * x/y)))

    cv2.imwrite(dir, imgResize, [cv2.IMWRITE_JPEG_QUALITY, 80])

def objectiveCartesian(pos, *args):

    # this function is the error function of x and y translations to minimise error 
    # between reference and target feature co-ordinates
    # Inputs:   (pos), translational vector to optimise
    #           (args), dictionary of the reference and target co-ordinates to fit for
    # Outputs:  (err), the squarred error of vectors given the shift pos

    ref = args[0]   # the first argument is ALWAYS the reference
    tar = args[1]   # the second argument is ALWAYS the target

    tarA = dictToArray(tar, float)
    refA = dictToArray(ref, float)

    # error calcuation
    err = np.sum((refA + pos - tarA)**2)
    # print(str(round(pos[0])) + ", " + str(round(pos[1])) + " evaluated with " + str(err) + " error score")

    return(err)      

def objectivePolar(w, centre, *args):

    # this function is the error function of rotations to minimise error 
    # between reference and target feature co-ordinates    
    # Inputs:   (w), angular translation to optimise
    #           (centre), optional to specify the centre which points are being rotated around
    #           (args), dictionary of the reference and target co-ordinates to fit for 
    #                   boolean on whether to return the error (for optimisation) or rot (for evaluation)
    #                   (minimising), if true then performing optimal fitting of target onto 
    #                   reference. If false then it is just rotating the points given to it as the target
    # Outputs:  (err), the squarred error of vectors given the shift pos
    #           (rot), the affine transform matrix used to (works on images)
    #           (tar), the new features after transforming

    minimising = args[0]
    tar = args[1]   # the second argument is ALWAYS the target, ie the one that is being fitted onto the reference
    if minimising:
        ref = args[2]   # the first argument is ALWAYS the reference, ie the one that isn't rotating
    
    try:
        plotting = args[3]
    except:
        plotting = False

    if type(w) is np.ndarray:
        w = w[0]

    
    tarN = {}

    tarA = dictToArray(tar, float)
    
    # if the centre is not specified, find it from the target points
    if np.sum(centre == None) == 1:
        centre = findCentre(tarA)       # this is the mean of all the features

    # find the centre of the target from the annotated points
    tarA = (tarA).astype(float)
    centre = (centre).astype(float)

    # debugging stuff --> shows that the rotational transformation is correct on the features
    # so it would suggest that the centre point on the image is not being matched up well
    
    # create an array to contain all the points found and rotated
    m = 1
    plotting = False

    # process per target feature
    tarNames = list(tar)

    # adjust the position of the features by w degrees
    for n in range(len(tarNames)):

        feat = tarNames[n]

        # find the feature relative to the centre
        featPos = tarA[n, :] - centre

        # calculate the distance from the centre
        hyp = np.sqrt(np.sum((featPos)**2))

        # if there is no length (ie rotating on the point of interest)
        # just skip
        if hyp == 0:
            tarN[feat] = tarA[n, :]
            continue

        # get the angle of the point relative to the horiztonal
        angle = findangle(tarA[n, :], centre)
        anglen = angle + w*np.pi/180

        # calculate the new position
        opp = hyp * np.sin(anglen)
        adj = hyp * np.cos(anglen)

        newfeatPos = np.array([opp, adj]).astype(float) + centre

        # if the features were inversed, un-inverse
        tarN[feat] = newfeatPos

        # if plotting: denseMatrixViewer([tarA[n], tarN[i], centre])

    
    if plotting: denseMatrixViewer([tarA, dictToArray(tarN), centre])

    # print(dictToArray(tarN))
    # print(tarA)

    # print("w = " + str(w))
    # if optimising, return the error. 
    # if not optimising, return the affine matrix used for the transform
    if minimising:

        tarNa = dictToArray(tarN, float)
        refa = dictToArray(ref, float)
        err = np.sum((tarNa - refa)**2)
        # error calculation
        # print("     err = " + str(err))
        return(err)  

    else:
        return(tarN)

def findCentre(pos, typeV = float):

    # find the mean of an array of points which represent the x and y positions
    # Inputs:   (pos), array
    # Outputs:  (centre), the mean of the x and y points (rounded and as an int)

    if type(pos) == dict:
        pos = dictToArray(pos, float)

    centre = np.array([np.mean(pos[:, 0]), np.mean(pos[:, 1])]).astype(typeV)

    return(centre)

if __name__ == "__main__":
    multiprocessing.set_start_method('spawn')

    # dataHome is where all the directories created for information are stored 
    dataSource = '/Volumes/USB/Testing1/'
    dataSource = '/Volumes/USB/H653/'
    dataSource = '/Volumes/Storage/H653A_11.3new/'
    dataSource = '/Volumes/USB/H710B_6.1/'
    dataSource = '/Volumes/USB/H671B_18.5/'
    dataSource = '/Volumes/USB/H750A_7.0/'
    dataSource = '/Volumes/USB/H673A_7.6/'
    dataSource = '/Volumes/USB/H671A_18.5/'
    dataSource = '/Volumes/USB/Test/'
    dataSource = '/Volumes/Storage/H710C_6.1/'
    dataSource = '/Volumes/Storage/H653A_11.3/'

    # dataTrain = dataHome + 'FeatureID/'
    name = ''
    size = 3
    cpuNo = False

    align(dataSource, size, cpuNo, False, "png")
