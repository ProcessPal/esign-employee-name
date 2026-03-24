/**
 * PDF encryption with configurable permissions.
 *
 * Based on @pdfsmaller/pdf-encrypt-lite (MIT), adapted to support
 * custom permission flags (print-only) instead of the hardcoded
 * "all allowed" value in the upstream library.
 *
 * Uses the library's exported crypto primitives (md5, RC4).
 */

import {
  PDFDocument,
  PDFName,
  PDFHexString,
  PDFString,
  PDFDict,
  PDFArray,
  PDFRawStream,
  PDFNumber,
} from "pdf-lib";
import { md5, RC4, hexToBytes, bytesToHex } from "@pdfsmaller/pdf-encrypt-lite";

// Standard PDF padding string (from PDF specification)
const PADDING = new Uint8Array([
  0x28, 0xbf, 0x4e, 0x5e, 0x4e, 0x75, 0x8a, 0x41, 0x64, 0x00, 0x4e, 0x56,
  0xff, 0xfa, 0x01, 0x08, 0x2e, 0x2e, 0x00, 0xb6, 0xd0, 0x68, 0x3e, 0x80,
  0x2f, 0x0c, 0xa9, 0xfe, 0x64, 0x53, 0x69, 0x7a,
]);

// Print-only: bit 3 (print) + bits 13-31 (required by revision 3)
const PERMISSIONS_PRINT_ONLY = 0xfffff004 | 0; // signed: -4092

function padPassword(password) {
  const pwdBytes = new TextEncoder().encode(password);
  const padded = new Uint8Array(32);
  if (pwdBytes.length >= 32) {
    padded.set(pwdBytes.slice(0, 32));
  } else {
    padded.set(pwdBytes);
    padded.set(PADDING.slice(0, 32 - pwdBytes.length), pwdBytes.length);
  }
  return padded;
}

function computeEncryptionKey(userPassword, ownerKey, permissions, fileId) {
  const paddedPwd = padPassword(userPassword);
  const hashInput = new Uint8Array(
    paddedPwd.length + ownerKey.length + 4 + fileId.length
  );
  let offset = 0;
  hashInput.set(paddedPwd, offset);
  offset += paddedPwd.length;
  hashInput.set(ownerKey, offset);
  offset += ownerKey.length;
  hashInput[offset++] = permissions & 0xff;
  hashInput[offset++] = (permissions >> 8) & 0xff;
  hashInput[offset++] = (permissions >> 16) & 0xff;
  hashInput[offset++] = (permissions >> 24) & 0xff;
  hashInput.set(fileId, offset);

  let hash = md5(hashInput);
  for (let i = 0; i < 50; i++) hash = md5(hash.slice(0, 16));
  return hash.slice(0, 16);
}

function computeOwnerKey(ownerPassword, userPassword) {
  const paddedOwner = padPassword(ownerPassword || userPassword);
  let hash = md5(paddedOwner);
  for (let i = 0; i < 50; i++) hash = md5(hash);

  const paddedUser = padPassword(userPassword);
  let result = new Uint8Array(paddedUser);
  for (let i = 0; i < 20; i++) {
    const key = new Uint8Array(hash.length);
    for (let j = 0; j < hash.length; j++) key[j] = hash[j] ^ i;
    result = new RC4(key.slice(0, 16)).process(result);
  }
  return result;
}

function computeUserKey(encryptionKey, fileId) {
  const hashInput = new Uint8Array(PADDING.length + fileId.length);
  hashInput.set(PADDING);
  hashInput.set(fileId, PADDING.length);
  const hash = md5(hashInput);

  let result = new RC4(encryptionKey).process(hash);
  for (let i = 1; i <= 19; i++) {
    const key = new Uint8Array(encryptionKey.length);
    for (let j = 0; j < encryptionKey.length; j++) key[j] = encryptionKey[j] ^ i;
    result = new RC4(key).process(result);
  }
  const finalResult = new Uint8Array(32);
  finalResult.set(result);
  return finalResult;
}

function encryptObject(data, objectNum, generationNum, encryptionKey) {
  const keyInput = new Uint8Array(encryptionKey.length + 5);
  keyInput.set(encryptionKey);
  keyInput[encryptionKey.length] = objectNum & 0xff;
  keyInput[encryptionKey.length + 1] = (objectNum >> 8) & 0xff;
  keyInput[encryptionKey.length + 2] = (objectNum >> 16) & 0xff;
  keyInput[encryptionKey.length + 3] = generationNum & 0xff;
  keyInput[encryptionKey.length + 4] = (generationNum >> 8) & 0xff;
  const objectKey = md5(keyInput);
  return new RC4(objectKey.slice(0, Math.min(encryptionKey.length + 5, 16))).process(data);
}

function encryptStringsInObject(obj, objectNum, generationNum, encryptionKey) {
  if (!obj) return;
  if (obj instanceof PDFString) {
    const encrypted = encryptObject(obj.asBytes(), objectNum, generationNum, encryptionKey);
    obj.value = Array.from(encrypted).map((b) => String.fromCharCode(b)).join("");
  } else if (obj instanceof PDFHexString) {
    const encrypted = encryptObject(obj.asBytes(), objectNum, generationNum, encryptionKey);
    obj.value = bytesToHex(encrypted);
  } else if (obj instanceof PDFDict) {
    for (const [key, value] of obj.entries()) {
      const keyName = key.asString();
      if (keyName !== "/Length" && keyName !== "/Filter" && keyName !== "/DecodeParms") {
        encryptStringsInObject(value, objectNum, generationNum, encryptionKey);
      }
    }
  } else if (obj instanceof PDFArray) {
    for (const element of obj.asArray()) {
      encryptStringsInObject(element, objectNum, generationNum, encryptionKey);
    }
  }
}

/**
 * Encrypt a PDF with print-only permissions.
 * Empty user password (opens freely), random owner password (prevents editing).
 */
export async function encryptPdfPrintOnly(pdfBytes) {
  const pdfDoc = await PDFDocument.load(pdfBytes, {
    ignoreEncryption: true,
    updateMetadata: false,
  });

  const context = pdfDoc.context;
  const trailer = context.trailerInfo;

  // Get or generate file ID
  let fileId;
  const idArray = trailer.ID;
  if (idArray && Array.isArray(idArray) && idArray.length > 0) {
    const hexStr = idArray[0].toString().replace(/^<|>$/g, "");
    fileId = hexToBytes(hexStr);
  } else {
    fileId = new Uint8Array(16);
    crypto.getRandomValues(fileId);
    const idHex1 = PDFHexString.of(bytesToHex(fileId));
    const idHex2 = PDFHexString.of(bytesToHex(fileId));
    trailer.ID = [idHex1, idHex2];
  }

  // Generate random owner password
  const ownerPwdBytes = new Uint8Array(32);
  crypto.getRandomValues(ownerPwdBytes);
  const ownerPassword = bytesToHex(ownerPwdBytes);
  const userPassword = ""; // opens without prompt

  const permissions = PERMISSIONS_PRINT_ONLY;
  const ownerKey = computeOwnerKey(ownerPassword, userPassword);
  const encryptionKey = computeEncryptionKey(userPassword, ownerKey, permissions, fileId);
  const userKey = computeUserKey(encryptionKey, fileId);

  // Encrypt all objects
  for (const [ref, obj] of context.enumerateIndirectObjects()) {
    const objectNum = ref.objectNumber;
    const generationNum = ref.generationNumber || 0;

    if (obj instanceof PDFDict) {
      const filter = obj.get(PDFName.of("Filter"));
      if (filter && filter.asString() === "/Standard") continue;
    }

    if (obj instanceof PDFRawStream && obj.dict) {
      const type = obj.dict.get(PDFName.of("Type"));
      if (type) {
        const typeName = type.toString();
        if (typeName === "/XRef" || typeName === "/Sig") continue;
      }
    }

    if (obj instanceof PDFRawStream) {
      obj.contents = encryptObject(obj.contents, objectNum, generationNum, encryptionKey);
      if (obj.dict) {
        encryptStringsInObject(obj.dict, objectNum, generationNum, encryptionKey);
      }
    } else {
      encryptStringsInObject(obj, objectNum, generationNum, encryptionKey);
    }
  }

  const encryptDict = context.obj({
    Filter: PDFName.of("Standard"),
    V: PDFNumber.of(2),
    R: PDFNumber.of(3),
    Length: PDFNumber.of(128),
    P: PDFNumber.of(permissions),
    O: PDFHexString.of(bytesToHex(ownerKey)),
    U: PDFHexString.of(bytesToHex(userKey)),
  });

  trailer.Encrypt = context.register(encryptDict);

  return pdfDoc.save({ useObjectStreams: false });
}
