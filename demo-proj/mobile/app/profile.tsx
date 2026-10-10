import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { api, ApiError, fixture, Profile } from '../lib/api';
import { useSession, supabase } from '../lib/session';
import { Button, ErrorText, Field, Screen, styles } from '../components/ui';
const moveIn = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
const initial = { name: '', bio: '', budgetMin: '900', budgetMax: '1400', area: 'Wiedikon', moveIn,
  smoking: 'no', pets: 'none', sleep: 'regular', longitude: '8.518', latitude: '47.369', photoPath: '' };
export default function Onboarding() {
  const { token } = useSession(), cache = useQueryClient();
  const [form, setForm] = useState(initial);
  const profile = useQuery({ queryKey: ['profile'], queryFn: async () => {
    try { return await api<Profile>('/me/profile', token); }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
  }, enabled: !!token });
  useEffect(() => {
    if (!profile.data) return;
    const p = profile.data;
    setForm({ name: p.name, bio: p.bio, budgetMin: String(p.budgetMin), budgetMax: String(p.budgetMax), area: p.area, moveIn: p.moveIn.slice(0,10), smoking: p.smoking, pets: p.pets, sleep: p.sleep, longitude: String(p.longitude), latitude: String(p.latitude), photoPath: p.photoPath ?? '' });
  }, [profile.data]);
  const save = useMutation({ mutationFn: () => api<Profile>('/me/profile', token, {
    ...form, photoPath: form.photoPath || undefined, budgetMin: Number(form.budgetMin), budgetMax: Number(form.budgetMax), longitude: Number(form.longitude), latitude: Number(form.latitude),
  }, 'PUT'), onSuccess: () => { cache.invalidateQueries(); router.push('/discover'); } });
  const photo = useMutation({ mutationFn: async () => {
    const upload = await api<{ mode: string; path: string; token: string }>('/me/photo-upload', token, {});
    if (fixture) { setForm(f => ({ ...f, photoPath: upload.path })); return; }
    const selection = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsEditing: true, quality: 0.7 });
    if (selection.canceled) return;
    const asset = selection.assets[0];
    if (asset.mimeType !== 'image/jpeg') throw new Error('Choose a JPEG photo for this demo.');
    if (asset.fileSize && asset.fileSize > 5 * 1024 * 1024) throw new Error('Photo must be under 5 MB');
    const file = await fetch(asset.uri, { signal: AbortSignal.timeout(10000) });
    const bytes = await file.arrayBuffer();
    if (bytes.byteLength > 5 * 1024 * 1024) throw new Error('Photo must be under 5 MB');
    const { error } = await supabase!.storage.from('profile-photos').uploadToSignedUrl(upload.path, upload.token, bytes, { contentType: 'image/jpeg' });
    if (error) throw new Error('Photo upload failed; check Supabase Storage configuration');
    setForm(f => ({ ...f, photoPath: upload.path }));
  } });
  return <Screen title="Your roommate profile">
    {!token ? <Text style={styles.text}>Sign in on Home first.</Text> : <>
      <Text style={styles.text}>Budgets are monthly CHF. Choose an approximate area location; precise addresses aren’t needed.</Text>
      {(['name','bio','budgetMin','budgetMax','area','moveIn','longitude','latitude'] as const).map(key => <Field key={key} label={key === 'moveIn' ? 'Move-in (YYYY-MM-DD)' : key} value={form[key]} numeric={['budgetMin','budgetMax','longitude','latitude'].includes(key)} onChange={value => setForm(f => ({ ...f, [key]: value }))} />)}
      {([{ key: 'smoking', values: ['no','yes','outside'] }, { key: 'pets', values: ['none','cat','dog','other'] }, { key: 'sleep', values: ['early','regular','late'] }] as const).map(group => <View key={group.key} style={{ gap: 8 }}>
        <Text style={styles.label}>{group.key}</Text><View style={styles.row}>{group.values.map(value => <Button key={value} title={`${form[group.key] === value ? '✓ ' : ''}${value}`} onPress={() => setForm(f => ({ ...f, [group.key]: value }))} />)}</View>
      </View>)}
      <Button title={fixture ? 'Add simulated photo' : 'Choose JPEG photo'} disabled={photo.isPending} onPress={() => photo.mutate()} />
      {form.photoPath ? <Text style={styles.text}>{fixture ? 'Photo simulated with an initial avatar.' : 'Photo uploaded; save profile to attach it.'}</Text> : null}
      <Button title="Save and discover" disabled={save.isPending || photo.isPending || profile.isPending} onPress={() => save.mutate()} />
    </>}
    <ErrorText error={profile.error ?? save.error ?? photo.error} />
  </Screen>;
}
