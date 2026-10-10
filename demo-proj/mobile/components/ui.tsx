import { ReactNode } from 'react';
import { ScrollView, Text, TextInput, View, Pressable, StyleSheet } from 'react-native';
import { Link } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { fixture } from '../lib/api';
export const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#FAF7F2' }, content: { padding: 24, gap: 16 },
  title: { fontSize: 32, fontWeight: '800', color: '#292038' }, text: { fontSize: 16, color: '#40364C', lineHeight: 24 },
  label: { fontSize: 13, fontWeight: '700', color: '#6C5B7B' },
  input: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#D9CFDF', borderRadius: 12, padding: 12, fontSize: 16, color: '#292038' },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  card: { backgroundColor: '#FFFFFF', padding: 24, borderRadius: 24, gap: 12 },
  button: { backgroundColor: '#7351A2', padding: 14, borderRadius: 14, alignItems: 'center' },
  buttonText: { color: '#FFFFFF', fontWeight: '700', fontSize: 16 },
  error: { color: '#A3273C', lineHeight: 22 },
});
export function Screen({ title, children }: { title: string; children: ReactNode }) {
  return <SafeAreaView style={styles.page}><ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
    <Text style={styles.label}>FLATPAL · {fixture ? 'FIXTURE DEMO' : 'LIVE PROVIDERS'}</Text>
    <Text style={styles.title}>{title}</Text>
    <View style={styles.row}><Link href="/" style={styles.text}>Home</Link><Link href="/profile" style={styles.text}>Profile</Link><Link href="/discover" style={styles.text}>Discover</Link><Link href="/matches" style={styles.text}>Matches</Link></View>
    {children}
  </ScrollView></SafeAreaView>;
}
export function Button({ title, onPress, disabled = false }: { title: string; onPress: () => void; disabled?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button, disabled && { opacity: 0.5 }]}><Text style={styles.buttonText}>{title}</Text></Pressable>;
}
export function Field({ label, value, onChange, numeric = false, secret = false }: { label: string; value: string; onChange: (value: string) => void; numeric?: boolean; secret?: boolean }) {
  return <View style={{ gap: 6 }}><Text style={styles.label}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChange} style={styles.input} keyboardType={numeric ? 'numeric' : 'default'} secureTextEntry={secret} autoCapitalize="none" /></View>;
}
export function ErrorText({ error }: { error: unknown }) { return error ? <Text accessibilityRole="alert" style={styles.error}>{error instanceof Error ? error.message : 'Request failed'}</Text> : null; }
