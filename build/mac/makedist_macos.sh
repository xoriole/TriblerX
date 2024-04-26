#!/usr/bin/env bash
set -x # print all commands
set -e # exit when any command fails

# Script to build Tribler 64-bit on Mac
# Initial author(s): Riccardo Petrocco, Arno Bakker

APPNAME=Tribler
LOG_LEVEL=${LOG_LEVEL:-"DEBUG"}
BUILD_ENV=${BUILD_ENV:-"venv"}

if [ -e .TriblerVersion ]; then
    DMGNAME="Tribler-$(cat .TriblerVersion)"
fi

export RESOURCES=build/mac/resources

# ----- Clean up
/bin/rm -rf dist

# ----- Prepare venv & install dependencies before the build

python3 -m venv "${BUILD_ENV}"
. "${BUILD_ENV}"/bin/activate
python3 -m pip install --upgrade -r requirements-build.txt

# ----- Build

echo Building Tribler using PyInstaller
pyinstaller tribler.spec --log-level="${LOG_LEVEL}"

mkdir -p dist/installdir
mv dist/$APPNAME.app dist/installdir

# From original Makefile
# Background
mkdir -p dist/installdir/.background
cp $RESOURCES/background.png dist/installdir/.background

# Volume Icon
cp $RESOURCES/VolumeIcon.icns dist/installdir/.VolumeIcon.icns

# Shortcut to /Applications
ln -s /Applications dist/installdir/Applications

touch dist/installdir

mkdir -p dist/temp

# Sign the app if environment variables are set
if [ -n "$CODE_SIGN_ENABLED" ] && [ -n "$APPLE_DEV_ID" ]; then
    echo "Signing $APPNAME.app with ID: $APPLE_DEV_ID"
    SIGN_MSG="Developer ID Application: $APPLE_DEV_ID"
    codesign --deep --force --verbose --sign "$SIGN_MSG" --options runtime dist/installdir/$APPNAME.app
fi

# create image
hdiutil create -fs HFS+ -srcfolder dist/installdir -format UDRW -scrub -volname ${APPNAME} dist/$APPNAME.dmg

# open it
hdiutil attach -readwrite -noverify -noautoopen dist/$APPNAME.dmg -mountpoint dist/temp/mnt

# make sure root folder is opened when image is
bless --folder dist/temp/mnt --openfolder dist/temp/mnt
# hack: wait for completion
sleep 1

# Arno, 2011-05-15: Snow Leopard gives diff behaviour, so set initial 1000 bounds to normal size
# and added close/open after set position, following
# http://stackoverflow.com/questions/96882/how-do-i-create-a-nice-looking-dmg-for-mac-os-x-using-command-line-tools

# position items
# oddly enough, 'set f .. as alias' can fail, but a reboot fixes that
osascript -e "tell application \"Finder\"" \
-e "   set f to POSIX file (\"${PWD}/dist/temp/mnt\" as string) as alias" \
-e "   tell folder f" \
-e "       open" \
-e "       tell container window" \
-e "          set toolbar visible to false" \
-e "          set statusbar visible to false" \
-e "          set current view to icon view" \
-e "          delay 1 -- Sync" \
-e "          set the bounds to {50, 100, 600, 400} -- Big size so the finder won't do silly things" \
-e "       end tell" \
-e "       delay 1 -- Sync" \
-e "       set icon size of the icon view options of container window to 128" \
-e "       set arrangement of the icon view options of container window to not arranged" \
-e "       set background picture of the icon view options of container window to file \".background:background.png\"" \
-e "       set position of item \"${APPNAME}.app\" to {150, 140}" \
-e "       set position of item \"Applications\" to {410, 140}" \
-e "       set the bounds of the container window to {50, 100, 600, 400}" \
-e "       close" \
-e "       open" \
-e "       update without registering applications" \
-e "       delay 5 -- Sync" \
-e "       close" \
-e "   end tell" \
-e "   -- Sync" \
-e "   delay 5" \
-e "end tell" || true

# turn on custom volume icon
SetFile -a C dist/temp/mnt || true

# close
hdiutil detach dist/temp/mnt || true

# make read-only
mv dist/$APPNAME.dmg dist/temp/rw.dmg
hdiutil convert dist/temp/rw.dmg -format UDZO -imagekey zlib-level=9 -o dist/$APPNAME.dmg
rm -f dist/temp/rw.dmg

if [ ! -z "$DMGNAME" ]; then
    mv dist/$APPNAME.dmg dist/$DMGNAME.dmg
fi


# Sign the dmg package and verify it
if [ -n "$CODE_SIGN_ENABLED" ] && [ -n "$APPLE_DEV_ID" ]; then
    codesign --force --verify --verbose --sign "$SIGN_MSG" dist/$DMGNAME.dmg
    codesign --verify --verbose=4 dist/$DMGNAME.dmg
    spctl --assess --type open --context context:primary-signature -v dist/$DMGNAME.dmg

    # Assuming the keychain profile with the signing key is created and named as "tribler-codesign-profile".
    # If not create the keychain profile with the following command:
    # xcrun notarytool store-credentials "tribler-codesign-profile" --apple-id "<dev-id-email>" --team-id "<dev-id-team>"
    KEYCHAIN_PROFILE=${KEYCHAIN_PROFILE:-"tribler-codesign-profile"}
    # Submit the DMG for notarization and staple afterwards
    xcrun notarytool submit dist/$DMGNAME.dmg --keychain-profile "$KEYCHAIN_PROFILE" --wait
    xcrun stapler staple dist/$DMGNAME.dmg
fi
