import base64
import hashlib
import struct
import enum
import datetime

import attr


__author__ = 'EasyPost <oss@easypost.com>'
version_info = (1, 1, 0)
__version__ = '.'.join(str(s) for s in version_info)


class SSHCertificateParserError(Exception):
    pass


@attr.s(frozen=True, hash=True, cmp=True)
class UnsupportedKeyTypeError(SSHCertificateParserError):
    """This key has a type which we do not know how to parse"""
    key_type = attr.ib()


@attr.s(frozen=True, cmp=True, hash=True)
class UnsupportedCertificateTypeError(SSHCertificateParserError):
    """This key was signed with an unknown certificate algorithm"""
    cert_type = attr.ib()


class CertType(enum.Enum):
    SSH2_CERT_TYPE_USER = 1
    SSH2_CERT_TYPE_HOST = 2


@attr.s
class PublicKey(object):
    raw = attr.ib()

    @property
    def fingerprint(self):
        dgt = hashlib.sha256(self.raw).digest()
        b64 = base64.standard_b64encode(dgt).decode('ascii')
        return 'SHA256:{0}'.format(b64.rstrip('='))


@attr.s
class RSAPublicKey(PublicKey):
    modulus = attr.ib()
    exponent = attr.ib()


def take_u32(byte_array):
    return struct.unpack('!L', byte_array[:4])[0], byte_array[4:]


def take_u64(byte_array):
    return struct.unpack('!Q', byte_array[:8])[0], byte_array[8:]


def take_pascal_bytestring(byte_array):
    string_len, rest = take_u32(byte_array)
    return rest[:string_len], rest[string_len:]


def take_pascal_string(byte_array):
    string_len, rest = take_u32(byte_array)
    return rest[:string_len].decode('utf-8'), rest[string_len:]


def take_list(byte_array, per_item_callback):
    overall, rest = take_pascal_bytestring(byte_array)
    lst = []
    while overall:
        item, overall = per_item_callback(overall)
        lst.append(item)
    return lst, rest


def take_rsa_cert(raw_pubkey, byte_array):
    modulus_len, byte_array = take_u32(byte_array)
    modulus = byte_array[:modulus_len]
    byte_array = byte_array[modulus_len:]
    exponent_len, byte_array = take_u32(byte_array)
    exponent = byte_array[:exponent_len]
    return RSAPublicKey(modulus=modulus, exponent=exponent, raw=raw_pubkey)


@attr.s
class SSHCertificate(object):
    serial = attr.ib()
    cert_type = attr.ib()
    key_id = attr.ib()
    principals = attr.ib()
    valid_after = attr.ib()
    valid_before = attr.ib()
    crits = attr.ib()
    exts = attr.ib()
    ca = attr.ib()
    signature = attr.ib()
    key_type = attr.ib()
    pubkey_parts = attr.ib()

    def asdict(self):
        dct = attr.asdict(self)
        del dct['ca']
        dct['valid_after'] = dct['valid_after'].isoformat()
        dct['valid_before'] = dct['valid_before'].isoformat()
        dct['cert_type'] = dct['cert_type'].name
        dct['signature'] = base64.b64encode(dct['signature']).decode('ascii')
        dct['ca_fingerprint'] = self.ca.fingerprint
        dct['pubkey_parts'] = dict(
            (k, base64.b64encode(v).decode('ascii'))
            for k, v in
            dct['pubkey_parts'].items()
        )
        return dct

    @classmethod
    def from_bytes(cls, byte_array):
        if ' ' in byte_array:
            blob = byte_array.split(' ')[1]
        else:
            blob = byte_array
        blob = base64.b64decode(blob)
        key_type, blob = take_pascal_string(blob)
        pubkey_parts = {}
        if key_type == 'ssh-rsa-cert-v01@openssh.com':
            pubkey_parts['nonce'], blob = take_pascal_bytestring(blob)
            pubkey_parts['n'], blob = take_pascal_bytestring(blob)
            pubkey_parts['e'], blob = take_pascal_bytestring(blob)
        elif key_type == 'ssh-ed25519-cert-v01@openssh.com':
            pubkey_parts['nonce'], blob = take_pascal_bytestring(blob)
            pubkey_parts['pubkey'], blob = take_pascal_bytestring(blob)
        elif key_type == 'ssh-dss-cert-v01@openssh.com':
            pubkey_parts['nonce'], blob = take_pascal_bytestring(blob)
            pubkey_parts['p'], blob = take_pascal_bytestring(blob)
            pubkey_parts['q'], blob = take_pascal_bytestring(blob)
            pubkey_parts['g'], blob = take_pascal_bytestring(blob)
            pubkey_parts['pubkey'], blob = take_pascal_bytestring(blob)
        else:
            raise UnsupportedKeyTypeError(key_type)
        serial, blob = take_u64(blob)
        cert_type, blob = take_u32(blob)
        cert_type = CertType(cert_type)
        key_id, blob = take_pascal_string(blob)
        principals, blob = take_list(blob, take_pascal_string)
        valid_after, blob = take_u64(blob)
        valid_after = datetime.datetime.utcfromtimestamp(valid_after)
        valid_before, blob = take_u64(blob)
        valid_before = datetime.datetime.utcfromtimestamp(valid_before)
        crits, blob = take_list(blob, take_pascal_string)
        exts, blob = take_list(blob, take_pascal_string)
        unknown, blob = take_pascal_bytestring(blob)
        raw_ca, blob = take_pascal_bytestring(blob)
        ca_cert_type, raw_ca_rest = take_pascal_string(raw_ca)
        if ca_cert_type == 'ssh-rsa':
            ca_cert = take_rsa_cert(raw_ca, raw_ca_rest)
        else:
            raise UnsupportedCertificateTypeError(ca_cert_type)
        signature = blob
        return SSHCertificate(
            serial, cert_type, key_id, principals, valid_after, valid_before,
            crits, exts, ca_cert, signature, key_type, pubkey_parts
        )


__all__ = ['SSHCertificate']