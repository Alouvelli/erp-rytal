import { useEffect, useState } from 'react';
import { userApi } from '../../services/api';
import { User } from '../../types';
import { PlusIcon, TrashIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

const ROLE_BADGE: Record<string, string> = {
  ADMIN: 'badge-red', SCOLARITE: 'badge-yellow', TEACHER: 'badge-blue', STUDENT: 'badge-green',
};

export default function UsersTab() {
  const [users, setUsers] = useState<User[]>([]);
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const { register, handleSubmit, reset, watch } = useForm();
  const role = watch('role');

  const load = () => userApi.getAll().then(({ data }) => setUsers(data.data));
  useEffect(() => { load(); }, []);

  const create = async (data: any) => {
    try {
      await userApi.create(data);
      toast.success('Utilisateur créé');
      setShowModal(false); reset(); load();
    } catch (e: any) { toast.error(e.response?.data?.message || 'Erreur'); }
  };

  const remove = async (id: string) => {
    if (!confirm('Désactiver cet utilisateur ?')) return;
    await userApi.delete(id);
    toast.success('Utilisateur désactivé');
    load();
  };

  const filtered = users.filter(u =>
    `${u.firstName} ${u.lastName} ${u.email}`.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-4">
      <div className="flex gap-3 items-center">
        <input className="input flex-1 max-w-xs" placeholder="Rechercher..." value={search} onChange={e => setSearch(e.target.value)} />
        <button onClick={() => setShowModal(true)} className="btn-primary">
          <PlusIcon className="w-4 h-4" /> Nouvel utilisateur
        </button>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
            <tr>
              {['Nom', 'Email', 'Rôle', 'Statut', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
            {filtered.map(u => (
              <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                <td className="px-4 py-3 font-medium">{u.firstName} {u.lastName}</td>
                <td className="px-4 py-3 text-gray-500">{u.email}</td>
                <td className="px-4 py-3"><span className={`badge ${ROLE_BADGE[u.role]}`}>{u.role}</span></td>
                <td className="px-4 py-3">
                  <span className={`badge ${(u as any).isActive ? 'badge-green' : 'badge-gray'}`}>{(u as any).isActive ? 'Actif' : 'Inactif'}</span>
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => remove(u.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg">
                    <TrashIcon className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold mb-4">Nouvel utilisateur</h2>
            <form onSubmit={handleSubmit(create)} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Prénom</label>
                  <input className="input" {...register('firstName', { required: true })} />
                </div>
                <div>
                  <label className="label">Nom</label>
                  <input className="input" {...register('lastName', { required: true })} />
                </div>
              </div>
              <div>
                <label className="label">Email</label>
                <input type="email" className="input" {...register('email', { required: true })} />
              </div>
              <div>
                <label className="label">Mot de passe</label>
                <input type="password" className="input" {...register('password', { required: true, minLength: 8 })} />
              </div>
              <div>
                <label className="label">Rôle</label>
                <select className="input" {...register('role', { required: true })}>
                  <option value="">Choisir...</option>
                  <option value="ADMIN">Administrateur</option>
                  <option value="SCOLARITE">Scolarité</option>
                  <option value="TEACHER">Enseignant</option>
                  <option value="STUDENT">Étudiant</option>
                </select>
              </div>
              {role === 'TEACHER' && (
                <div>
                  <label className="label">Département</label>
                  <input className="input" {...register('department')} placeholder="Ex: Informatique" />
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Créer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
